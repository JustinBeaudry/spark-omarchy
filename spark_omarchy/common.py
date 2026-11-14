"""Shared paths, ownership checks and private atomic state writes."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parent.parent
SERVICE = 'spark-omarchy.service'
SLICE = 'spark-omarchy.slice'
DESKTOP = 'spark-omarchy.desktop'
OAUTH_DESKTOP = 'spark-omarchy-oauth.desktop'
UPDATE_SERVICE = 'spark-omarchy-update.service'
UPDATE_TIMER = 'spark-omarchy-update.timer'
NATIVE_UPDATER_CONFIG = '{"features":{"autoUpdaterDisabled":true}}'
SCHEMES = frozenset({
    'com.readdle.spark.auth-bridge.desktop-dist',
    'com.googleusercontent.apps.681834923750-3p9205dgnfbq0s196910u38tmn61ehc2',
    'hotmail.com.readdle.smartmail.desktop',
    'msauth.com.readdle.smartmail.desktop',
    'yahoo.com.readdle.smartmail.desktop',
    'oauth.redirect.com.readdle.smartmail',
})


class Error(RuntimeError):
    """An actionable error safe to display without including callback data."""


def run(args, *, env=None, capture=False, quiet=False, check=True):
    options = {'env': env, 'check': False, 'text': True}
    if quiet:
        options.update(stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    elif capture:
        options.update(stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        result = subprocess.run([str(a) for a in args], **options)
    except OSError as exc:
        raise Error(f'Cannot execute {Path(str(args[0])).name}: {exc.strerror}') from None
    if check and result.returncode:
        # Never echo argv: OAuth URLs may contain single-use secrets.
        raise Error(f'{Path(str(args[0])).name} failed (exit {result.returncode}).')
    return result


def executable(name):
    path = shutil.which(name)
    if not path:
        raise Error(f'Missing {name}; see the prerequisites in README.md.')
    return path


def atomic_write(path, text, mode=0o600):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.' + path.name + '.', dir=path.parent)
    try:
        os.fchmod(fd, mode)
        with os.fdopen(fd, 'w', encoding='utf-8') as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


class Paths:
    def __init__(self, home=None, env=None):
        env = os.environ if env is None else env
        self.home = Path.home() if home is None else Path(home)
        def xdg(key, fallback):
            value = Path(env.get(key) or fallback)
            if not value.is_absolute() or any(ord(c) < 32 for c in str(value)):
                raise Error(f'{key} must be an absolute path without control characters.')
            return value
        self.data_base = xdg('XDG_DATA_HOME', self.home / '.local/share')
        self.config_base = xdg('XDG_CONFIG_HOME', self.home / '.config')
        self.cache_base = xdg('XDG_CACHE_HOME', self.home / '.cache')
        self.data = self.data_base / 'spark-omarchy'
        self.prefix = self.data / 'prefix'
        self.app_dir = self.prefix / 'drive_c/SparkOmarchy'
        self.app = self.app_dir / 'Spark Desktop.exe'
        self.runtime = self.data / 'runtime'
        self.cache = self.cache_base / 'spark-omarchy'
        self.state_file = self.data / 'state.json'
        self.bin = self.home / '.local/bin/spark-omarchy'
        self.applications = self.data_base / 'applications'
        self.units = self.config_base / 'systemd/user'

    def environment(self):
        env = os.environ.copy()
        env.update(WINEPREFIX=str(self.prefix),
                   WINEDLLOVERRIDES='spkenv=n;winemenubuilder.exe=d;mscoree,mshtml=d',
                   WINEDEBUG='-all', NODE_CONFIG=NATIVE_UPDATER_CONFIG)
        return env

    def state(self, required=False):
        if self.data.is_symlink() or self.state_file.is_symlink():
            raise Error('Refusing a symlinked managed data directory/state file.')
        if not self.state_file.exists():
            if required:
                raise Error('Not installed; run spark-omarchy install first.')
            return None
        try:
            state = json.loads(self.state_file.read_text())
        except (ValueError, OSError):
            raise Error('Invalid installation state; preserve it and see troubleshooting.') from None
        if state.get('project') != 'spark-omarchy' or state.get('schema') != 1:
            raise Error('This data directory is not owned by a recognized spark-omarchy install.')
        return state

    def save(self, state):
        atomic_write(self.state_file, json.dumps(state, indent=2, sort_keys=True) + '\n')

    def check_not_root(self):
        if os.geteuid() == 0:
            raise Error('Run as your desktop user, not root/sudo. Only package installation needs root.')


def prefix_processes(paths):
    """Check local process metadata only; never return environment contents."""
    needle = ('WINEPREFIX=' + str(paths.prefix)).encode()
    found = []
    for proc in Path('/proc').iterdir():
        if not proc.name.isdigit():
            continue
        try:
            if needle in (proc / 'environ').read_bytes().split(b'\0'):
                found.append(int(proc.name))
        except (PermissionError, FileNotFoundError, ProcessLookupError):
            continue
    return found


def manifest():
    return json.loads((ROOT / 'manifest.json').read_text())


def current_manifest(state):
    """Installed app approvals evolve independently of integration code releases."""
    data = state.get('release_manifest') or manifest()
    if not isinstance(data, dict) or not isinstance(data.get('spark_version'), str):
        raise Error('Installed application manifest is invalid.')
    if state.get('prepared') and state.get('spark_version') != data['spark_version']:
        raise Error('Installed version and approval metadata disagree; preserve state for recovery.')
    return data
