"""Public CLI. Never include callback URLs in diagnostics or subprocess errors."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import platform
import shutil
import sys
from urllib.parse import urlsplit
import uuid
from . import __version__
from .common import (OAUTH_DESKTOP, SCHEMES, SERVICE, SLICE, UPDATE_SERVICE, UPDATE_TIMER,
                     NATIVE_UPDATER_CONFIG, Error, Paths, current_manifest,
                     executable, manifest, prefix_processes, run)
from .installer import install, install_lock, get_shim, validate_shim, copy_runtime
from .integration import install_integration, query_handler, uninstall_integration
from .vendor import digest
from . import updater


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
            'WINEDEBUG=-all', 'NODE_CONFIG=' + NATIVE_UPDATER_CONFIG,
            executable('wine'), str(paths.app), *arguments]


def active():
    return run(['systemctl', '--user', 'is-active', '--quiet', SERVICE], quiet=True, check=False).returncode == 0


def start(paths, callback=None):
    state = paths.state(required=True)
    if not state.get('integrated'):
        raise Error('Desktop integration missing; run spark-omarchy repair.')
    arguments = callback_arguments(callback) if callback is not None else []
    lock_path = paths.data / 'launch.lock'
    if lock_path.is_symlink():
        raise Error('Refusing a symlinked launch lock.')
    with lock_path.open('a') as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        if (paths.data / 'update-transaction.json').exists():
            raise Error('Interrupted update detected. Run spark-omarchy update --recover before starting.')
        state = paths.state(required=True)
        updater.validate_app(paths.app_dir, current_manifest(state), state.get('shim_sha256'))
        running = active()
        if not running:
            if callback is not None:
                raise Error('Spark is closed. Open Spark and begin a fresh sign-in; the old callback cannot resume it.')
            if state.get('last_update'):
                # Conservative even if launch fails: do not promise that no data
                # migration ran. Offline snapshots remain for manual recovery.
                state['last_update']['launched'] = True
                paths.save(state)
        else:
            run(forwarding_command(paths, arguments), env=paths.environment(), quiet=True)
            return
    # The service's pre-start guard takes the lifecycle lock itself. Do not
    # hold it across systemctl start, which waits for that guard to finish.
    run(['systemctl', '--user', 'start', SERVICE], quiet=True)


def guard_start(paths):
    with updater.launch_lock(paths):
        if (paths.data / 'update-transaction.json').exists():
            raise Error('Interrupted update: recover it before starting Spark.')
        state = paths.state(required=True)
        updater.validate_app(paths.app_dir, current_manifest(state), state.get('shim_sha256'))
        if state.get('last_update'):
            state['last_update']['launched'] = True
            paths.save(state)


def stop(paths):
    paths.state(required=True)
    run(['systemctl', '--user', 'stop', SERVICE], quiet=True)


def doctor(paths):
    state = paths.state()
    data = current_manifest(state) if state else manifest()
    checks = {}
    for name in ('wine', 'wineboot', 'wineserver', '7z', 'curl', 'systemctl',
                 'systemd-run', 'xdg-mime', 'update-desktop-database', 'openssl'):
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
    checks['no_interrupted_update'] = not (paths.data / 'update-transaction.json').exists()
    unit = paths.units / SERVICE
    checks['native_updater_control_configured'] = unit.is_file() and 'autoUpdaterDisabled' in unit.read_text()
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


def configure_updates(paths, action):
    state = paths.state(required=True)
    if not state.get('integrated'):
        raise Error('Install/repair desktop integration before configuring automatic checks.')
    for name in (UPDATE_SERVICE, UPDATE_TIMER):
        path = paths.units / name
        if not path.is_file() or path.is_symlink() or str(path) not in state.get('owned_files', []):
            raise Error('Update units are missing or unowned. Upgrade the client and run repair first.')
    if action == 'status':
        result = run(['systemctl', '--user', 'is-enabled', '--quiet', UPDATE_TIMER], quiet=True, check=False)
        print('enabled (checks/downloads only)' if result.returncode == 0 else 'disabled')
        return
    if action == 'enable':
        executable('openssl')
        executable('notify-send')
        run(['systemctl', '--user', 'enable', '--now', UPDATE_TIMER], quiet=True)
    else:
        # Stop a running downloader before taking its nonblocking install lock.
        run(['systemctl', '--user', 'disable', '--now', UPDATE_TIMER], quiet=True)
        run(['systemctl', '--user', 'stop', UPDATE_SERVICE], quiet=True)
    with install_lock(paths):
        state = paths.state(required=True)
        state['updates_enabled'] = action == 'enable'
        paths.save(state)
    print('Daily checks/downloads enabled; installation always requires approval.' if action == 'enable' else 'Automatic checks/downloads disabled.')


def update_command(paths, args):
    if args.background and (not args.download or args.yes):
        raise Error('Background mode requires --download and can never apply an update.')
    if args.yes and (args.check or args.download or args.recover):
        raise Error('--yes is only valid when explicitly applying an update.')
    if args.recover:
        result = updater.recover(paths)
    elif args.check or args.download:
        result = updater.check(paths, download=args.download, background=args.background)
    else:
        result = updater.check(paths)
        if result['status'] == 'available':
            if not args.yes:
                if not os.isatty(0):
                    raise Error('Run update in a terminal to approve installation, or use --download only.')
                answer = input(f"Download and apply approved Spark {result['available']} after making an offline backup? Spark must be closed. [y/N] ")
                if answer.lower() not in ('y', 'yes'):
                    print('Cancelled; no application update applied.')
                    return
            updater.assert_idle(paths)
            confirmed = result['available']
            downloaded = updater.check(paths, download=True)
            if downloaded.get('available') != confirmed:
                raise Error('Recommended target changed; review and confirm the update again.')
            result = updater.apply(paths, yes=True, expected_version=confirmed)
    if not args.background:
        print(json.dumps(result, sort_keys=True))
        if result.get('status') == 'downloaded':
            print('Quit Spark, then run spark-omarchy update to approve application.')
        elif result.get('status') == 'applied':
            print('Update applied; Spark was not launched. Rollback is available only before first launch.')


def parser():
    p = argparse.ArgumentParser(description='Unofficial, per-user Spark Desktop integration for Omarchy.')
    p.add_argument('--version', action='version', version=__version__)
    sub = p.add_subparsers(dest='command', required=True)
    setup = sub.add_parser('install', help='Download/prepare the reviewed vendor build and install user integration')
    setup.add_argument('--accept-vendor-terms', action='store_true', help='Confirm that you reviewed and accept Spark\'s terms/privacy policy')
    setup.add_argument('--installer', type=Path, help='Use an existing installer; its pinned SHA-256 is still required')
    setup.add_argument('--no-integrate', action='store_true', help='Prepare app/prefix only; do not change desktop handlers or units')
    sub.add_parser('start', help='Open/show Spark without a hard CPU limit')
    sub.add_parser('guard-start', help='Internal service pre-start integrity and update-lifecycle guard')
    sub.add_parser('stop', help='Stop this dedicated prefix (prefer normal window close to save state)')
    sub.add_parser('status', help='Print service state without reading mail/logs')
    sub.add_parser('repair', help='Restore owned desktop integration, preserving previous OAuth handlers')
    update = sub.add_parser('update', help='Check/download approved updates; apply only after explicit confirmation')
    mode = update.add_mutually_exclusive_group()
    mode.add_argument('--check', action='store_true', help='Check signed approval metadata only')
    mode.add_argument('--download', action='store_true', help='Download verified installer only; never apply')
    mode.add_argument('--recover', action='store_true', help='Recover an interrupted application switch without launching Spark')
    update.add_argument('--background', action='store_true', help='Timer mode: requires --download and never applies')
    update.add_argument('--yes', action='store_true', help='Explicit noninteractive approval to back up and apply while Spark is closed')
    rollback = sub.add_parser('rollback', help='Revert application files only before the updated app has been launched')
    rollback.add_argument('--yes', action='store_true')
    automatic = sub.add_parser('updates', help='Opt in/out of daily signed update checks/downloads')
    automatic.add_argument('action', choices=('enable', 'disable', 'status'))
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
        elif args.command == 'guard-start':
            guard_start(paths)
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
                shim = get_shim()
                validate_shim(shim)
                copy_runtime(paths, shim)
                install_integration(paths, state)
            print('Desktop integration repaired.')
        elif args.command == 'updates':
            configure_updates(paths, args.action)
        elif args.command == 'update':
            update_command(paths, args)
        elif args.command == 'rollback':
            print(json.dumps(updater.rollback(paths, yes=args.yes)))
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
        if args.command == 'update' and args.background and 'paths' in locals():
            try:
                updater.notify_failure(paths)
            except (Error, OSError, ValueError):
                pass
        message = 'Spark callback failed; run spark-omarchy doctor and start a fresh sign-in.' if args.command == 'open-url' else str(exc)
        print('spark-omarchy: ' + message, file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print('Interrupted. No automatic data deletion was performed.', file=sys.stderr)
        return 130
