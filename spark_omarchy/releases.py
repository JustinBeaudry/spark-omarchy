"""Authenticate a bounded, expiring approved-release catalog before parsing it."""
import base64
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re
import tempfile
from .common import Error, ROOT, executable, run

FEED_URL = 'https://raw.githubusercontent.com/JustinBeaudry/spark-omarchy/main/updates/stable.json'
MAX_FEED = 262144
BUNDLE = 'resources/app.asar.unpacked/node_modules/@readdle/sparkcore-win/bin/Release/SparkCore.bundle'
HASH_FIELDS = ('installer_sha256', 'foundation_sha256', 'patched_foundation_sha256',
               'app_sha256', 'asar_sha256')


def version(value, parts=4):
    if not isinstance(value, str) or len(value) > 64 or not re.fullmatch(r'[0-9]+(?:\.[0-9]+){' + str(parts - 1) + r'}', value):
        raise Error('Invalid release version.')
    return tuple(int(v) for v in value.split('.'))


def json_object(data):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise Error('Duplicate metadata field.')
            result[key] = value
        return result
    try:
        return json.loads(data, object_pairs_hook=unique,
                          parse_constant=lambda _: (_ for _ in ()).throw(Error('Invalid JSON number.')))
    except (ValueError, UnicodeError, TypeError, RecursionError):
        raise Error('Invalid release metadata JSON.') from None


def validate_release(release):
    if not isinstance(release, dict):
        raise Error('Invalid approved release.')
    app_version = release.get('spark_version')
    version(app_version)
    version(release.get('minimum_client'), 3)
    if release.get('bundle_relative') != BUNDLE:
        raise Error('Unsupported bundle layout; a newer integration client is required.')
    if release.get('installer_url') != f'https://downloads.sparkmailapp.com/Spark3/win/dist/{app_version}/Spark.exe':
        raise Error('Approved release must use the canonical HTTPS vendor URL.')
    for field in HASH_FIELDS:
        if not isinstance(release.get(field), str) or not re.fullmatch('[0-9a-f]{64}', release[field]):
            raise Error('Missing or invalid approved artifact checksum.')
    if type(release.get('shim_abi')) is not int or release['shim_abi'] != 1:
        raise Error('Unsupported shim ABI; update the integration client first.')
    if release.get('native_updater_control') != 'node-config-v1':
        raise Error('Native-updater control has not been qualified for this release.')
    return release


def validate_catalog(catalog, now=None):
    now = datetime.now(timezone.utc) if now is None else now
    if not isinstance(catalog, dict) or type(catalog.get('schema')) is not int or catalog['schema'] != 1:
        raise Error('Unsupported release catalog schema.')
    if catalog.get('channel') != 'stable' or type(catalog.get('sequence')) is not int or catalog['sequence'] < 1:
        raise Error('Invalid release channel or sequence.')
    try:
        issued = datetime.strptime(catalog['issued_at'], '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc)
        expires = datetime.strptime(catalog['expires_at'], '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc)
    except (KeyError, TypeError, ValueError):
        raise Error('Invalid catalog validity period.') from None
    if issued > now + timedelta(minutes=10) or expires <= now or expires <= issued or expires - issued > timedelta(days=120):
        raise Error('Catalog is expired or its validity period is invalid; check your clock or refresh approvals.')
    releases = catalog.get('releases')
    if not isinstance(releases, list) or not 1 <= len(releases) <= 32:
        raise Error('Invalid approved release list.')
    seen = set()
    for release in releases:
        validate_release(release)
        key = release['spark_version']
        if key in seen:
            raise Error('Duplicate approved version.')
        seen.add(key)
    if not isinstance(catalog.get('recommended'), str) or catalog['recommended'] not in seen:
        raise Error('Recommended version is not in the approved catalog.')
    return catalog


def verify_envelope(data, *, public_key=None, now=None):
    if not isinstance(data, bytes) or len(data) > MAX_FEED:
        raise Error('Release catalog is too large or invalid.')
    envelope = json_object(data)
    if not isinstance(envelope, dict) or type(envelope.get('schema')) is not int or envelope['schema'] != 1:
        raise Error('Invalid signed release envelope.')
    try:
        payload = base64.b64decode(envelope['payload'], validate=True)
        signature = base64.b64decode(envelope['signature'], validate=True)
    except (KeyError, ValueError, TypeError):
        raise Error('Invalid signed release encoding.') from None
    if len(signature) != 64 or len(payload) > MAX_FEED:
        raise Error('Invalid release signature length/payload size.')
    key = ROOT / 'trust/updates.pem' if public_key is None else Path(public_key)
    if not key.is_file():
        raise Error('Update trust key missing; reinstall the integration client.')
    with tempfile.TemporaryDirectory(prefix='spark-signature-') as temporary:
        root = Path(temporary)
        (root / 'payload').write_bytes(payload)
        (root / 'signature').write_bytes(signature)
        result = run([executable('openssl'), 'pkeyutl', '-verify', '-pubin', '-inkey', key,
                      '-rawin', '-in', root / 'payload', '-sigfile', root / 'signature'], quiet=True, check=False)
        if result.returncode:
            raise Error('Release signature verification failed. No update will be used.')
    # Parse potentially structured release data only after authenticity checks.
    return validate_catalog(json_object(payload), now)
