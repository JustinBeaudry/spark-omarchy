"""User-owned desktop integration with selective OAuth rollback."""
import shutil
from . import __version__
from .common import (DESKTOP, OAUTH_DESKTOP, SCHEMES, SERVICE, SLICE,
                     UPDATE_SERVICE, UPDATE_TIMER, NATIVE_UPDATER_CONFIG,
                     Error, atomic_write, executable, run)


def unit_quote(value, *, arguments=False):
    value = str(value)
    if any(ord(c) < 32 for c in value):
        raise Error('Control characters are not supported in desktop paths.')
    value = value.replace('\\', '\\\\').replace('"', '\\"').replace('%', '%%')
    if arguments:
        value = value.replace('$', '$$')
    return '"' + value + '"'


def desktop_quote(value):
    value = str(value)
    if any(ord(c) < 32 for c in value):
        raise Error('Control characters are not supported in desktop paths.')
    escaped = ''.join('\\' + c if c in '\\"`$' else c for c in value)
    return '"' + escaped.replace('\\', '\\\\').replace('%', '%%') + '"'


def xdg_environment(paths):
    return '\n'.join('Environment=' + unit_quote(key + '=' + str(value)) for key, value in (
        ('XDG_DATA_HOME', paths.data_base), ('XDG_CONFIG_HOME', paths.config_base),
        ('XDG_CACHE_HOME', paths.cache_base)))


def service_text(paths, wine, wineserver):
    return f'''[Unit]
Description=Spark Mail (unofficial Wine integration)

[Service]
Type=exec
Slice={SLICE}
Environment={unit_quote('WINEPREFIX=' + str(paths.prefix))}
Environment="WINEDLLOVERRIDES=spkenv=n;winemenubuilder.exe=d;mscoree,mshtml=d"
Environment=WINEDEBUG=-all
{xdg_environment(paths)}
Environment={unit_quote('NODE_CONFIG=' + NATIVE_UPDATER_CONFIG)}
WorkingDirectory={str(paths.app_dir).replace('%', '%%')}
ExecStartPre={unit_quote(paths.bin, arguments=True)} guard-start
ExecStart={unit_quote(wine, arguments=True)} {unit_quote(paths.app, arguments=True)}
# Spark performs its own quit on normal window close; clean leftover helpers.
# A server that has already exited is not an error; cgroup cleanup still applies.
ExecStop=-{unit_quote(wineserver, arguments=True)} -k
KillMode=control-group
TimeoutStopSec=10
StandardOutput=null
StandardError=null
Restart=no
'''


def update_service_text(paths):
    return f'''[Unit]
Description=Check and download approved Spark updates (never apply)

[Service]
Type=oneshot
{xdg_environment(paths)}
ExecStart={unit_quote(paths.bin, arguments=True)} update --download --background
Nice=10
UMask=0077
NoNewPrivileges=yes
TimeoutStartSec=20min
StandardOutput=null
StandardError=null
'''


def update_timer_text():
    return '''[Unit]
Description=Daily approved Spark update check (opt-in)

[Timer]
OnActiveSec=2min
OnCalendar=daily
RandomizedDelaySec=30min
Persistent=true
Unit=spark-omarchy-update.service

[Install]
WantedBy=timers.target
'''


def desktop_text(paths, oauth=False):
    text = f'''[Desktop Entry]
Type=Application
Name={'Spark Mail OAuth Bridge' if oauth else 'Spark Mail'}
Comment=Unofficial Spark Desktop integration through Wine
Exec={desktop_quote(paths.bin)} {'open-url %u' if oauth else 'start'}
Icon=spark-omarchy
Terminal=false
'''
    if oauth:
        return text + 'NoDisplay=true\nMimeType=' + ''.join('x-scheme-handler/' + s + ';' for s in sorted(SCHEMES)) + '\n'
    return text + 'Categories=Network;Email;\nStartupWMClass=spark desktop.exe\n'


def query_handler(scheme):
    return run(['xdg-mime', 'query', 'default', 'x-scheme-handler/' + scheme], capture=True).stdout.strip()


def owned_files(paths):
    return [paths.bin, paths.units / SERVICE, paths.units / SLICE,
            paths.units / UPDATE_SERVICE, paths.units / UPDATE_TIMER,
            paths.applications / DESKTOP, paths.applications / OAUTH_DESKTOP,
            paths.data_base / 'icons/hicolor/256x256/apps/spark-omarchy.png']


def preflight_integration(paths, state):
    for name in ('systemctl', 'systemd-run', 'xdg-mime', 'update-desktop-database'):
        executable(name)
    run(['systemctl', '--user', 'show-environment'], quiet=True)
    known = set(state.get('owned_files', []))
    for path in owned_files(paths):
        if path.is_symlink() or (path.exists() and str(path) not in known):
            raise Error(f'Refusing to overwrite an unrelated integration file: {path}')


def install_integration(paths, state):
    preflight_integration(paths, state)
    # Persist rollback info before changing any defaults, including partial failure.
    previous = state.setdefault('previous_handlers', {})
    for scheme in sorted(SCHEMES):
        if scheme not in previous:
            current = query_handler(scheme)
            if current == OAUTH_DESKTOP:
                raise Error('OAuth handler already exists without rollback state; see troubleshooting.')
            previous[scheme] = current
    state['owned_files'] = [str(path) for path in owned_files(paths)]
    paths.save(state)
    backup = paths.data / 'backups'
    backup.mkdir(mode=0o700, exist_ok=True)
    for i, path in enumerate((paths.config_base / 'mimeapps.list', paths.applications / 'mimeapps.list')):
        target = backup / f'mimeapps-before-install-{i}.list'
        if path.is_file() and not target.exists():
            shutil.copyfile(path, target)
            target.chmod(0o600)
    if not paths.runtime.exists():
        raise Error('Runtime copy missing; rerun install.')
    entry = f'''#!/usr/bin/env python3
import os
import sys
os.environ.setdefault('XDG_DATA_HOME', {str(paths.data_base)!r})
os.environ.setdefault('XDG_CONFIG_HOME', {str(paths.config_base)!r})
os.environ.setdefault('XDG_CACHE_HOME', {str(paths.cache_base)!r})
sys.path.insert(0, {str(paths.runtime)!r})
from spark_omarchy.cli import main
sys.exit(main())
'''
    atomic_write(paths.bin, entry, 0o755)
    atomic_write(paths.units / SLICE, '[Unit]\nDescription=Spark Mail Wine processes (no CPU cap)\n\n[Slice]\nCPUWeight=100\n', 0o644)
    atomic_write(paths.units / SERVICE, service_text(paths, executable('wine'), executable('wineserver')), 0o644)
    atomic_write(paths.units / UPDATE_SERVICE, update_service_text(paths), 0o644)
    atomic_write(paths.units / UPDATE_TIMER, update_timer_text(), 0o644)
    atomic_write(paths.applications / DESKTOP, desktop_text(paths), 0o644)
    atomic_write(paths.applications / OAUTH_DESKTOP, desktop_text(paths, True), 0o644)
    icon = owned_files(paths)[-1]
    icon.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(paths.data / 'icon.png', icon)
    icon.chmod(0o644)
    run(['systemctl', '--user', 'daemon-reload'], quiet=True)
    run(['update-desktop-database', str(paths.applications)], quiet=True)
    for scheme in sorted(SCHEMES):
        run(['xdg-mime', 'default', OAUTH_DESKTOP, 'x-scheme-handler/' + scheme], quiet=True)
        if query_handler(scheme) != OAUTH_DESKTOP:
            raise Error('OAuth handler registration did not take effect; see troubleshooting.')
    state['integrated'] = True
    state['integration_client_version'] = __version__
    paths.save(state)


def remove_association(text, scheme, desktop):
    """Remove only our desktop ID, leaving other defaults and comments alone."""
    key = 'x-scheme-handler/' + scheme
    lines = []
    section = ''
    for line in text.splitlines(keepends=True):
        stripped = line.strip()
        if stripped.startswith('[') and stripped.endswith(']'):
            section = stripped[1:-1]
        if section in ('Default Applications', 'Added Associations', 'Removed Associations') and '=' in line:
            name, value = line.split('=', 1)
            if name.strip() == key:
                values = [v for v in value.strip().split(';') if v and v != desktop]
                if desktop in value.strip().split(';'):
                    if values:
                        lines.append(name + '=' + ';'.join(values) + ';\n')
                    continue
        lines.append(line)
    return ''.join(lines)


def uninstall_integration(paths, state):
    if str(paths.units / UPDATE_TIMER) in state.get('owned_files', []):
        run(['systemctl', '--user', 'disable', '--now', UPDATE_TIMER], quiet=True, check=False)
        run(['systemctl', '--user', 'stop', UPDATE_SERVICE], quiet=True, check=False)
    # Never restore a whole old mimeapps.list: newer user choices must survive.
    for scheme, previous in state.get('previous_handlers', {}).items():
        if scheme not in SCHEMES:
            raise Error('Unrecognized protocol in installation state.')
        if query_handler(scheme) == OAUTH_DESKTOP and previous:
            run(['xdg-mime', 'default', previous, 'x-scheme-handler/' + scheme], quiet=True)
        for path in (paths.config_base / 'mimeapps.list', paths.applications / 'mimeapps.list'):
            if path.is_file() and not path.is_symlink():
                text = path.read_text()
                changed = remove_association(text, scheme, OAUTH_DESKTOP)
                if changed != text:
                    atomic_write(path, changed, path.stat().st_mode & 0o777)
    allowed = {str(p): p for p in owned_files(paths)}
    for value in state.get('owned_files', []):
        if value not in allowed:
            raise Error('Unexpected owned path in state; refusing deletion.')
        path = allowed[value]
        if path.is_symlink():
            raise Error('An integration file was replaced with a symlink; remove it manually.')
        if path.is_file():
            path.unlink()
    run(['systemctl', '--user', 'daemon-reload'], quiet=True)
    if paths.applications.exists():
        run(['update-desktop-database', str(paths.applications)], quiet=True)
    state['integrated'] = False
    state['updates_enabled'] = False
    state['owned_files'] = []
    state['previous_handlers'] = {}
    paths.save(state)
