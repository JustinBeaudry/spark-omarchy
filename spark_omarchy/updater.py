"""Approved downloads, explicit offline application switch, and crash recovery.

The timer never executes a vendor app or installs an update. Account data is
snapshotted offline before explicit application; post-launch schema rollback is
intentionally not automated.
"""
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import urllib.request
import uuid
from . import __version__
from .common import Error, atomic_write, current_manifest, prefix_processes, run
from .installer import download_installer, install_lock, prepare_app
from .releases import FEED_URL, MAX_FEED, verify_envelope, version
from .vendor import digest


def now_string():
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def read_json(path):
    if path.is_symlink():
        raise Error('Refusing symlinked update metadata.')
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        raise Error('Update metadata is missing or invalid; preserve it for recovery.') from None


def save_json(path, value):
    atomic_write(path, json.dumps(value, sort_keys=True, indent=2) + '\n')


def fetch_feed():
    try:
        request = urllib.request.Request(FEED_URL, headers={'User-Agent': 'spark-omarchy/' + __version__})
        with urllib.request.urlopen(request, timeout=25) as response:
            if response.geturl() != FEED_URL:
                raise Error('Unexpected catalog redirect.')
            data = response.read(MAX_FEED + 1)
    except OSError:
        raise Error('Cannot fetch approved-release catalog; no installed files were changed.') from None
    if len(data) > MAX_FEED:
        raise Error('Release catalog exceeds size limit.')
    return data


def accept_catalog(paths, envelope):
    catalog = verify_envelope(envelope)
    record_path = paths.data / 'update-state.json'
    record = read_json(record_path) if record_path.exists() else {}
    previous = record.get('highest_sequence', 0)
    if type(previous) is not int or previous < 0:
        raise Error('Invalid local catalog sequence state.')
    identity = hashlib.sha256(json.dumps(catalog, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    if catalog['sequence'] < previous:
        raise Error('Refusing a replayed older release catalog.')
    if catalog['sequence'] == previous and record.get('catalog_identity') != identity:
        raise Error('Catalog sequence was reused for different metadata.')
    record.update(highest_sequence=catalog['sequence'], catalog_identity=identity, last_check=now_string())
    save_json(record_path, record)
    release = next(r for r in catalog['releases'] if r['spark_version'] == catalog['recommended'])
    if version(release['minimum_client'], 3) > version(__version__, 3):
        raise Error('A newer integration client is required before this Spark update. Update the source/package first.')
    return catalog, release


def assert_idle(paths):
    if shutil.which('systemctl'):
        result = run(['systemctl', '--user', 'show', 'spark-omarchy.service',
                      '-p', 'ActiveState', '--value'], capture=True, check=False)
        if result.stdout and result.stdout.strip() in ('active', 'activating', 'deactivating', 'reloading'):
            raise Error('Spark service is starting/running/stopping. Wait for it to be fully stopped.')
    if prefix_processes(paths):
        raise Error('Spark/Wine is still running. Quit normally and wait; updates never force-close it.')


@contextmanager
def launch_lock(paths):
    path = paths.data / 'launch.lock'
    if path.is_symlink():
        raise Error('Refusing a symlinked launch lock.')
    with path.open('a') as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        yield


def check(paths, *, download=False, background=False):
    paths.state(required=True)
    with install_lock(paths):
        state = paths.state(required=True)
        if not state.get('prepared'):
            raise Error('Finish application preparation before checking updates.')
        if (paths.data / 'update-transaction.json').exists():
            raise Error('An interrupted update needs recovery first: spark-omarchy update --recover')
        validate_app(paths.app_dir, current_manifest(state), state.get('shim_sha256'))
        envelope = fetch_feed()
        _, release = accept_catalog(paths, envelope)
        installed = current_manifest(state)
        if version(release['spark_version']) <= version(installed['spark_version']):
            return {'status': 'current', 'installed': installed['spark_version']}
        if download:
            download_installer(paths, release, quiet=background)
            # Store the entire authenticated envelope, not an unsigned selection.
            atomic_write(paths.data / 'pending-update.json', envelope.decode())
            if background:
                notify_ready(paths, release['spark_version'])
        return {'status': 'downloaded' if download else 'available',
                'installed': installed['spark_version'], 'available': release['spark_version']}


def notify_ready(paths, target):
    record_path = paths.data / 'update-state.json'
    record = read_json(record_path)
    if record.get('notified_version') == target:
        return
    notify = shutil.which('notify-send')
    if notify:
        result = run([notify, '--app-name=Spark Omarchy', 'Spark update downloaded',
                      f'Approved Spark {target} is ready. Quit Spark, then run spark-omarchy update.'], quiet=True, check=False)
        if not result.returncode:
            record['notified_version'] = target
            save_json(record_path, record)


def notify_failure(paths):
    """Never race a notification write against monotonic approval-state writes."""
    if not paths.state_file.is_file():
        return
    with install_lock(paths):
        notify_failure_locked(paths)


def notify_failure_locked(paths):
    """Generic, rate-limited notification; no remote data or callback strings."""
    record_path = paths.data / 'update-state.json'
    record = read_json(record_path) if record_path.exists() else {}
    today = now_string()[:10]
    if record.get('error_notified_date') == today:
        return
    notify = shutil.which('notify-send')
    if notify:
        result = run([notify, '--app-name=Spark Omarchy', 'Spark update check failed',
                      'Run spark-omarchy update --check for details. Installed files were not updated.'],
                     quiet=True, check=False)
        if not result.returncode:
            record['error_notified_date'] = today
            save_json(record_path, record)


def validate_app(app, release, expected_shim=None):
    app = Path(app)
    for relative, key in (('Spark Desktop.exe', 'app_sha256'), ('resources/app.asar', 'asar_sha256'),
                          (release['bundle_relative'] + '/Foundation.dll', 'patched_foundation_sha256')):
        file = app / relative
        if not file.is_file() or (release.get(key) and digest(file) != release[key]):
            raise Error('Application integrity check failed; no unsafe repatching attempted.')
    if expected_shim is not None:
        shim = app / release['bundle_relative'] / 'spkenv.dll'
        if not shim.is_file() or digest(shim) != expected_shim:
            raise Error('Installed compatibility shim changed; repair it before launching.')


def version_dir(paths, value):
    version(value)
    root = paths.data / 'versions'
    target = root / value
    if root.is_symlink() or target.is_symlink():
        raise Error('Refusing symlinked version storage.')
    return target


def snapshot(paths, state):
    """Make an offline private copy, never following user-directory symlinks."""
    assert_idle(paths)
    if paths.prefix.is_symlink():
        raise Error('Refusing a symlinked prefix snapshot.')
    size = 0
    for directory, dirs, files in os.walk(paths.prefix, followlinks=False):
        if Path(directory) == paths.prefix / 'drive_c':
            dirs[:] = [name for name in dirs if name != 'SparkOmarchy']
        for name in files:
            path = Path(directory) / name
            if not path.is_symlink():
                size += path.stat().st_size
    if shutil.disk_usage(paths.data).free < size + 256 * 1024 * 1024:
        raise Error('Not enough free space for an offline prefix snapshot; no update applied.')
    identifier = 'update-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid.uuid4().hex
    parent = paths.data / 'backups'
    if parent.is_symlink() or paths.prefix.is_symlink():
        raise Error('Refusing symlinked backup/prefix storage.')
    parent.mkdir(mode=0o700, exist_ok=True)
    root = parent / identifier
    root.mkdir(mode=0o700)
    def ignore(directory, names):
        return ['SparkOmarchy'] if Path(directory) == paths.prefix / 'drive_c' else []
    shutil.copytree(paths.prefix, root / 'prefix', symlinks=True, ignore=ignore)
    save_json(root / 'state.json', state)
    if (paths.data / 'icon.png').is_file():
        shutil.copyfile(paths.data / 'icon.png', root / 'icon.png')
    save_json(root / 'snapshot.json', {'schema': 1, 'created_at': now_string(), 'app_excluded': True,
                                       'spark_version': state['spark_version']})
    return identifier


def replace_pointer(paths, target):
    temporary = paths.app_dir.parent / ('.SparkOmarchy-next-' + uuid.uuid4().hex)
    temporary.symlink_to(target, target_is_directory=True)
    try:
        os.replace(temporary, paths.app_dir)
    finally:
        temporary.unlink(missing_ok=True)


def copy_icon(paths, source):
    if source.is_symlink() or not source.is_file():
        raise Error('Version icon missing or symlinked.')
    for target in (paths.data / 'icon.png',
                   paths.data_base / 'icons/hicolor/256x256/apps/spark-omarchy.png'):
        if target.parent.exists():
            if target.is_symlink():
                raise Error('Refusing a symlinked icon destination.')
            fd, temporary = tempfile.mkstemp(prefix='.spark-icon-', dir=target.parent)
            try:
                with os.fdopen(fd, 'wb') as output, source.open('rb') as original:
                    shutil.copyfileobj(original, output)
                os.chmod(temporary, 0o644 if target.name == 'spark-omarchy.png' else 0o600)
                os.replace(temporary, target)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)


def recover_transaction(paths):
    """Call only under install + launch locks. No app has run via managed start."""
    journal = paths.data / 'update-transaction.json'
    if not journal.exists():
        return False
    assert_idle(paths)
    transaction = read_json(journal)
    if transaction.get('schema') != 1:
        raise Error('Unknown update journal; preserve it for manual recovery.')
    before = transaction['before_state']
    old = current_manifest(before)
    target = version_dir(paths, old['spark_version'])
    if target.is_dir() and (target / 'app').is_dir():
        validate_app(target / 'app', old)
        if paths.app_dir.exists() and not paths.app_dir.is_symlink():
            raise Error('Unexpected real application directory during recovery.')
        replace_pointer(paths, target / 'app')
        copy_icon(paths, target / 'icon.png')
    else:
        # Failure before the original real directory was migrated.
        if paths.app_dir.is_symlink():
            raise Error('Original application backup missing; manual recovery required.')
        validate_app(paths.app_dir, old)
        if transaction.get('migrating_original') and target.is_dir():
            # The journal was written before making this metadata-only folder.
            # Remove an incomplete migration only if no unexpected files exist.
            if any(p.name not in ('icon.png', 'release.json') for p in target.iterdir()):
                raise Error('Unexpected partial migration files; preserve them for manual recovery.')
            shutil.rmtree(target)
    paths.save(before)
    journal.unlink()
    return True


def switch_app(paths, before, after):
    """Journal the one-time directory migration and atomically swap the pointer."""
    old = current_manifest(before)
    new = current_manifest(after)
    old_root = version_dir(paths, old['spark_version'])
    new_root = version_dir(paths, new['spark_version'])
    validate_app(paths.app_dir, old)
    validate_app(new_root / 'app', new)
    if paths.app_dir.is_symlink():
        if paths.app_dir.resolve() != (old_root / 'app').resolve():
            raise Error('Application pointer is outside recognized version storage.')
    elif old_root.exists():
        raise Error('Original version storage already exists; preserve it and investigate.')
    journal = paths.data / 'update-transaction.json'
    save_json(journal, {'schema': 1, 'before_state': before, 'after_state': after,
                        'migrating_original': not paths.app_dir.is_symlink()})
    try:
        if not paths.app_dir.is_symlink():
            old_root.mkdir(parents=True, mode=0o700)
            shutil.copyfile(paths.data / 'icon.png', old_root / 'icon.png')
            save_json(old_root / 'release.json', old)
            paths.app_dir.rename(old_root / 'app')
        replace_pointer(paths, new_root / 'app')
        paths.save(after)
        copy_icon(paths, new_root / 'icon.png')
        journal.unlink()
    except BaseException:
        # SIGKILL/power loss leaves a journal; managed start refuses it until
        # explicit recovery. Ordinary failures recover before propagating.
        recover_transaction(paths)
        raise


def apply(paths, *, yes=False, expected_version=None):
    paths.state(required=True)
    if not yes:
        if not os.isatty(0):
            raise Error('Application requires confirmation. Use --yes explicitly or run in a terminal.')
        answer = input('Apply the downloaded approved update while Spark is closed? An offline prefix backup will be kept. [y/N] ')
        if answer.lower() not in ('y', 'yes'):
            return {'status': 'cancelled'}
    with install_lock(paths), launch_lock(paths):
        assert_idle(paths)
        if (paths.data / 'update-transaction.json').exists():
            raise Error('Recover the interrupted transaction first: update --recover')
        before = paths.state(required=True)
        if not before.get('integrated') or version(before.get('integration_client_version', '0.0.0'), 3) < (0, 2, 0):
            raise Error('Upgrade/repair desktop integration first; application requires the update-aware service guard.')
        envelope_path = paths.data / 'pending-update.json'
        if not envelope_path.is_file() or envelope_path.is_symlink():
            raise Error('No approved download pending. Run spark-omarchy update --download first.')
        _, release = accept_catalog(paths, envelope_path.read_bytes())
        if version(before['integration_client_version'], 3) < version(release['minimum_client'], 3):
            raise Error('Repair integration with the required newer client before applying this release.')
        if expected_version is not None and release['spark_version'] != expected_version:
            raise Error('Approved target changed after confirmation; review and confirm the update again.')
        if version(release['spark_version']) <= version(before['spark_version']):
            raise Error('Pending version is not newer; no automatic downgrades or same-version replacement.')
        source = paths.cache / ('Spark-' + release['spark_version'] + '.exe')
        if source.is_symlink() or not source.is_file() or digest(source) != release['installer_sha256']:
            raise Error('Downloaded installer missing or changed; download it again.')
        old = current_manifest(before)
        validate_app(paths.app_dir, old)
        shim = paths.app_dir / old['bundle_relative'] / 'spkenv.dll'
        if not shim.is_file() or digest(shim) != before['shim_sha256']:
            raise Error('Installed shim changed; repair the integration before updating.')
        target = version_dir(paths, release['spark_version'])
        target.parent.mkdir(mode=0o700, exist_ok=True)
        if target.exists():
            # A previously rolled-back or interrupted staged version can be
            # reused only if its approval and critical files still match.
            if read_json(target / 'release.json') != release:
                raise Error('Existing target metadata differs; preserve it for investigation.')
            validate_app(target / 'app', release)
            if digest(target / 'app' / release['bundle_relative'] / 'spkenv.dll') != before['shim_sha256']:
                raise Error('Existing target shim differs from this installation.')
            backup = snapshot(paths, before)
        else:
            with tempfile.TemporaryDirectory(prefix='update-stage-', dir=paths.data) as staging:
                stage = Path(staging)
                app = prepare_app(source, release, shim, stage)
                validate_app(app, release)
                backup = snapshot(paths, before)
                assert_idle(paths)
                # Publish only a complete version directory. An interruption
                # before this rename leaves disposable staging, not an unusable
                # canonical target that would block all subsequent retries.
                prepared = stage / 'prepared-version'
                prepared.mkdir(mode=0o700)
                app.rename(prepared / 'app')
                shutil.copyfile(stage / 'icon.png', prepared / 'icon.png')
                save_json(prepared / 'release.json', release)
                prepared.rename(target)
        assert_idle(paths)
        after = dict(before)
        after.update(spark_version=release['spark_version'], release_manifest=release,
                     last_update={'backup': backup, 'previous_version': before['spark_version'],
                                  'launched': False, 'applied_at': now_string()})
        switch_app(paths, before, after)
        envelope_path.unlink(missing_ok=True)
        return {'status': 'applied', 'installed': release['spark_version'], 'backup': backup}


def recover(paths):
    paths.state(required=True)
    with install_lock(paths), launch_lock(paths):
        return {'status': 'recovered' if recover_transaction(paths) else 'nothing-to-recover'}


def rollback(paths, *, yes=False):
    if not yes:
        raise Error('Rollback requires --yes. It is allowed only before the updated app has been launched.')
    paths.state(required=True)
    with install_lock(paths), launch_lock(paths):
        assert_idle(paths)
        if (paths.data / 'update-transaction.json').exists():
            raise Error('Recover the interrupted transaction first.')
        state = paths.state(required=True)
        last = state.get('last_update', {})
        if not last or last.get('launched'):
            raise Error('Automatic rollback is unsafe after launch (possible data migrations). Preserve data and use the offline backup recovery guide.')
        identifier = last.get('backup', '')
        if not identifier.startswith('update-') or '/' in identifier or '\\' in identifier or '..' in identifier:
            raise Error('Invalid backup identifier.')
        original = read_json(paths.data / 'backups' / identifier / 'state.json')
        if original.get('project') != 'spark-omarchy' or original.get('spark_version') != last['previous_version']:
            raise Error('Backup metadata does not match this update.')
        switch_app(paths, state, original)
        return {'status': 'rolled-back', 'installed': original['spark_version']}
