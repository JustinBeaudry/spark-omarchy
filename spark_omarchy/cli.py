"""Public CLI. Never include callback URLs in diagnostics or subprocess errors."""
import argparse
import fcntl
import json
from pathlib import Path
import platform
import shutil
import sys
from urllib.parse import urlsplit
import uuid
from . import __version__
from .common import (OAUTH_DESKTOP, SCHEMES, SERVICE, SLICE,
                     Error, Paths, executable, manifest, prefix_processes, run)
from .installer import install, install_lock
from .integration import install_integration, query_handler, uninstall_integration
from .vendor import digest


def callback_arguments(url):
    if not isinstance(url, str) or not url or len(url) > 32768 or any(ord(c) < 32 for c in url):
        raise Error('Rejected invalid Spark callback.')
    try:
        scheme = urlsplit(url).scheme.lower()
    except ValueError:
        raise Error('Rejected invalid Spark callback.') from None
    if scheme not in SCHEMES:
        raise Error('Rejected unsupported Spark callback scheme.')
    return ['--win-open-url', '--', url]


def forwarding_command(paths, arguments):
    return [executable('systemd-run'), '--user', '--quiet', '--collect',
            '--unit=spark-omarchy-forward-' + uuid.uuid4().hex,
            '--slice=' + SLICE, '--service-type=exec',
            '--property=StandardOutput=null', '--property=StandardError=null',
            '--', executable('env'), 'WINEPREFIX=' + str(paths.prefix),
            'WINEDLLOVERRIDES=spkenv=n;winemenubuilder.exe=d;mscoree,mshtml=d',
            'WINEDEBUG=-all', executable('wine'), str(paths.app), *arguments]


def active():
    return run(['systemctl', '--user', 'is-active', '--quiet', SERVICE], quiet=True, check=False).returncode == 0


def start(paths, callback=None):
    state = paths.state(required=True)
    if not state.get('integrated'):
        raise Error('Desktop integration missing; run spark-omarchy repair.')
    data = manifest()
    foundation = paths.app_dir / data['bundle_relative'] / 'Foundation.dll'
    if not foundation.is_file() or digest(foundation) != data['patched_foundation_sha256']:
        raise Error('Vendor files changed or are missing; see troubleshooting. No unsafe automatic repatch attempted.')
    arguments = callback_arguments(callback) if callback is not None else []
    lock_path = paths.data / 'launch.lock'
    if lock_path.is_symlink():
        raise Error('Refusing a symlinked launch lock.')
    with lock_path.open('a') as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        running = active()
        if not running:
            if callback is not None:
                raise Error('Spark is closed. Open Spark and begin a fresh sign-in; the old callback cannot resume it.')
            run(['systemctl', '--user', 'start', SERVICE], quiet=True)
            return
        run(forwarding_command(paths, arguments), env=paths.environment(), quiet=True)


def stop(paths):
    paths.state(required=True)
    run(['systemctl', '--user', 'stop', SERVICE], quiet=True)


def doctor(paths):
    data = manifest()
    state = paths.state()
    checks = {}
    for name in ('wine', 'wineboot', 'wineserver', '7z', 'curl', 'systemctl',
                 'systemd-run', 'xdg-mime', 'update-desktop-database'):
        checks['tool_' + name] = bool(shutil.which(name))
    checks['x86_64'] = platform.machine().lower() in ('x86_64', 'amd64')
    checks['prepared'] = bool(state and state.get('prepared') and paths.app.is_file())
    checks['integrated'] = bool(state and state.get('integrated'))
    checks['icon_installed'] = (paths.data_base / 'icons/hicolor/256x256/apps/spark-omarchy.png').is_file()
    foundation = paths.app_dir / data['bundle_relative'] / 'Foundation.dll'
    checks['reviewed_patch_intact'] = foundation.is_file() and digest(foundation) == data['patched_foundation_sha256']
    service = {}
    if checks['tool_systemctl']:
        result = run(['systemctl', '--user', 'show', SERVICE, '-p', 'ActiveState', '-p', 'Result', '-p', 'MainPID'], capture=True, check=False)
        if not result.returncode:
            service = dict(line.split('=', 1) for line in result.stdout.splitlines() if '=' in line)
        slice_result = run(['systemctl', '--user', 'show', SLICE, '-p', 'CPUQuotaPerSecUSec', '--value'], capture=True, check=False)
        checks['no_hard_cpu_cap'] = not slice_result.returncode and slice_result.stdout.strip() == 'infinity'
    if checks['tool_xdg-mime'] and checks['integrated']:
        checks['oauth_handlers'] = all(query_handler(s) == OAUTH_DESKTOP for s in SCHEMES)
    version = 'not found'
    if checks['tool_wine']:
        version = run(['wine', '--version'], env=paths.environment(), capture=True, check=False).stdout.strip()
    return {'project_version': __version__, 'pinned_spark': data['spark_version'],
            'wine': version, 'checks': checks, 'service': service,
            'privacy': 'Metadata only. No account data, logs, cookies, URLs or dumps were read.'}


def uninstall(paths, purge=False, yes=False):
    paths.check_not_root()
    paths.state(required=True)
    if not yes:
        raise Error('Use --yes to remove integration. Mail data is kept unless --purge-data is explicitly supplied.')
    with install_lock(paths):
        state = paths.state(required=True)
        # Stop before touching runtime files. Failure is not silently ignored.
        if state.get('integrated'):
            stop(paths)
        elif paths.prefix.exists():
            # Wine returns 1 when there is no server to kill. Verify process
            # absence rather than treating an already-stopped prefix as broken.
            run(['wineserver', '-k'], env=paths.environment(), quiet=True, check=False)
        if prefix_processes(paths):
            raise Error('Prefix processes are still running; refusing to remove files/data.')
        if state.get('owned_files') or state.get('previous_handlers'):
            uninstall_integration(paths, state)
        if purge:
            if paths.prefix.is_symlink() or paths.data.is_symlink():
                raise Error('Refusing to purge symlinked data/prefix.')
            # The install lock is open but can safely be unlinked after all work.
            shutil.rmtree(paths.data)
        else:
            print('Integration removed. Prefix, account data and runtime retained for recovery.')
        print('Download cache retained. See docs/uninstall.md for optional cleanup.')


def parser():
    p = argparse.ArgumentParser(description='Unofficial, per-user Spark Desktop integration for Omarchy.')
    p.add_argument('--version', action='version', version=__version__)
    sub = p.add_subparsers(dest='command', required=True)
    setup = sub.add_parser('install', help='Download/prepare the reviewed vendor build and install user integration')
    setup.add_argument('--accept-vendor-terms', action='store_true', help='Confirm that you reviewed and accept Spark\'s terms/privacy policy')
    setup.add_argument('--installer', type=Path, help='Use an existing installer; its pinned SHA-256 is still required')
    setup.add_argument('--no-integrate', action='store_true', help='Prepare app/prefix only; do not change desktop handlers or units')
    sub.add_parser('start', help='Open/show Spark without a hard CPU limit')
    sub.add_parser('stop', help='Stop this dedicated prefix (prefer normal window close to save state)')
    sub.add_parser('status', help='Print service state without reading mail/logs')
    sub.add_parser('repair', help='Restore owned desktop integration, preserving previous OAuth handlers')
    diagnostics = sub.add_parser('doctor', help='Check metadata only; never collect mail, logs or auth URLs')
    diagnostics.add_argument('--json', action='store_true')
    callback = sub.add_parser('open-url', help='Internal OAuth handler; normally called by the browser')
    callback.add_argument('url', help='Sensitive callback argument; never paste a real URL into reports')
    remove = sub.add_parser('uninstall', help='Remove integration while retaining mail data by default')
    remove.add_argument('--yes', action='store_true')
    remove.add_argument('--purge-data', action='store_true', help='ALSO permanently delete this app\'s prefix/account data; not recoverable')
    return p


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        paths = Paths()
        paths.check_not_root()
        if args.command == 'install':
            install(paths, supplied=args.installer, accept_terms=args.accept_vendor_terms, no_integrate=args.no_integrate)
            print('Prepared successfully.' if args.no_integrate else 'Installed. Open Spark Mail, then disable Settings → General → Close application to tray.')
        elif args.command == 'start':
            start(paths)
        elif args.command == 'open-url':
            start(paths, args.url)
        elif args.command == 'stop':
            stop(paths)
        elif args.command == 'status':
            paths.state(required=True)
            print('running' if active() else 'stopped')
        elif args.command == 'repair':
            with install_lock(paths):
                state = paths.state(required=True)
                if not state.get('prepared') or not paths.app.is_file():
                    raise Error('App preparation is incomplete; see recovery instructions.')
                install_integration(paths, state)
            print('Desktop integration repaired.')
        elif args.command == 'doctor':
            result = doctor(paths)
            if args.json:
                print(json.dumps(result, indent=2))
            else:
                print(f"Spark {result['pinned_spark']} / {result['wine']}")
                for key, value in result['checks'].items():
                    print(('OK   ' if value else 'FAIL ') + key)
                print(result['privacy'])
            return 0 if all(result['checks'].values()) else 1
        elif args.command == 'uninstall':
            uninstall(paths, args.purge_data, args.yes)
        return 0
    except (Error, OSError, ValueError, KeyError) as exc:
        # Expected errors contain no callback arguments. Do not print traceback
        # locals or arbitrary external tool output on the OAuth entry point.
        message = 'Spark callback failed; run spark-omarchy doctor and start a fresh sign-in.' if args.command == 'open-url' else str(exc)
        print('spark-omarchy: ' + message, file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print('Interrupted. No automatic data deletion was performed.', file=sys.stderr)
        return 130
