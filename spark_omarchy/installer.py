"""Prepare a dedicated prefix and a pinned, locally patched vendor app."""
from contextlib import contextmanager
import fcntl
import os
from pathlib import Path
import platform
import shutil
import tempfile
from .common import Error, ROOT, executable, manifest, run
from .integration import install_integration, preflight_integration
from .vendor import digest, extract_icon, patch_foundation


@contextmanager
def install_lock(paths):
    if paths.data.is_symlink():
        raise Error('Managed data directory must not be a symlink.')
    paths.data.mkdir(mode=0o700, parents=True, exist_ok=True)
    lock = paths.data / 'install.lock'
    if lock.is_symlink():
        raise Error('Refusing a symlinked install lock.')
    with lock.open('a') as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise Error('Another install/uninstall is running.') from None
        yield


def get_shim():
    for path in (ROOT / 'native/spkenv.dll', ROOT / 'build/spkenv.dll'):
        if path.is_file():
            return path
    builder = ROOT / 'bin/build-shim'
    if not builder.is_file():
        raise Error('Shim missing. Reinstall the integration package or build from source.')
    run(['bash', str(builder)])
    return ROOT / 'build/spkenv.dll'


def validate_shim(path):
    from .pe import PE
    pe = PE(path)
    exports = {name for _, name in pe.exports()}
    if not {'GetAllUsersProfileDirectoryW', 'GetProfilesDirectoryW'} <= exports:
        raise Error('Shim is missing required Windows API exports.')
    # Require an exception/unwind directory, unlike the early Winelib prototype.
    if not pe.u32(pe.directories + 24):
        raise Error('Shim has no x64 unwind metadata; rebuild with a supported compiler.')


def download_installer(paths, data, supplied=None):
    if supplied:
        source = Path(supplied).expanduser().resolve()
        if not source.is_file() or digest(source) != data['installer_sha256']:
            raise Error('Installer checksum mismatch. Only the pinned vendor version is supported.')
        return source
    paths.cache.mkdir(mode=0o700, parents=True, exist_ok=True)
    target = paths.cache / ('Spark-' + data['spark_version'] + '.exe')
    if target.exists() and digest(target) == data['installer_sha256']:
        return target
    partial = target.with_suffix('.download')
    if partial.is_symlink() or target.is_symlink():
        raise Error('Refusing a symlinked installer cache file.')
    try:
        run([executable('curl'), '--fail', '--location', '--proto', '=https',
             '--proto-redir', '=https', '--tlsv1.2', '--retry', '2',
             '--connect-timeout', '20', '--max-time', '900',
             '--output', str(partial), data['installer_url']])
        if digest(partial) != data['installer_sha256']:
            raise Error('Downloaded installer checksum mismatch; no vendor code was executed.')
        os.replace(partial, target)
    finally:
        partial.unlink(missing_ok=True)
    return target


def copy_runtime(paths, shim):
    temporary = paths.data / 'runtime.new'
    if temporary.exists():
        if temporary.is_symlink():
            raise Error('Unexpected runtime staging symlink.')
        shutil.rmtree(temporary)
    temporary.mkdir(mode=0o700)
    shutil.copytree(ROOT / 'spark_omarchy', temporary / 'spark_omarchy',
                    ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    shutil.copyfile(ROOT / 'manifest.json', temporary / 'manifest.json')
    (temporary / 'native').mkdir()
    shutil.copyfile(shim, temporary / 'native/spkenv.dll')
    if paths.runtime.is_symlink():
        raise Error('Refusing a symlinked runtime directory.')
    if paths.runtime.exists():
        shutil.rmtree(paths.runtime)
    temporary.rename(paths.runtime)


def install(paths, *, supplied=None, accept_terms=False, no_integrate=False):
    paths.check_not_root()
    if platform.machine().lower() not in ('x86_64', 'amd64'):
        raise Error('This release supports x86_64 only.')
    if not accept_terms:
        raise Error('Read Spark\'s terms/privacy policy, then pass --accept-vendor-terms. See README.md.')
    for name in ('wine', 'wineboot', 'wineserver', '7z'):
        executable(name)
    data = manifest()
    with install_lock(paths):
        state = paths.state()
        if state and state.get('prepared'):
            if state.get('spark_version') != data['spark_version']:
                raise Error('Installed version differs; automatic upgrades are not supported.')
            if not paths.app.is_file():
                raise Error('Managed app is missing. Preserve data; see troubleshooting before reinstalling.')
            foundation = paths.app_dir / data['bundle_relative'] / 'Foundation.dll'
            if not foundation.is_file() or digest(foundation) != data['patched_foundation_sha256']:
                raise Error('Managed vendor files changed (possibly an auto-update); refusing an unsafe repair.')
            # Refresh only our runtime from the invoked source/package entry
            # point; never replace the account-bearing app/prefix here.
            shim = get_shim()
            validate_shim(shim)
            copy_runtime(paths, shim)
            if not no_integrate:
                install_integration(paths, state)
            return
        if state:
            raise Error('Incomplete preparation found. Preserve data and see recovery instructions.')
        if paths.prefix.exists() or paths.runtime.exists():
            raise Error('Unrecognized prefix/runtime exists. This tool never adopts or overwrites another prefix.')
        if any(p.name != 'install.lock' for p in paths.data.iterdir()):
            raise Error('Unrecognized files exist in the managed data directory; refusing to adopt them.')
        state = {'project': 'spark-omarchy', 'schema': 1, 'prepared': False,
                 'integrated': False, 'spark_version': data['spark_version']}
        if not no_integrate:
            preflight_integration(paths, state)
        shim = get_shim()
        validate_shim(shim)
        source = download_installer(paths, data, supplied)
        with tempfile.TemporaryDirectory(prefix='prepare-', dir=paths.data) as staging:
            stage = Path(staging)
            run(['7z', 'x', '-y', str(source), '-o' + str(stage / 'nsis'),
                 '$PLUGINSDIR/app-64.7z'], quiet=True)
            archive = stage / 'nsis/$PLUGINSDIR/app-64.7z'
            if not archive.is_file():
                raise Error('Pinned installer payload missing; extraction failed.')
            app = stage / 'app'
            run(['7z', 'x', '-y', str(archive), '-o' + str(app)], quiet=True)
            if not (app / 'Spark Desktop.exe').is_file():
                raise Error('Extracted app executable missing.')
            bundle = app / data['bundle_relative']
            foundation = bundle / 'Foundation.dll'
            backup = bundle / 'Foundation.dll.spark-omarchy-original'
            shutil.copyfile(foundation, backup)
            patch_foundation(backup, foundation, data['foundation_sha256'],
                             data['patched_foundation_sha256'])
            shutil.copyfile(shim, bundle / 'spkenv.dll')
            extract_icon(app / 'Spark Desktop.exe', stage / 'icon.png')
            # Save an incomplete marker before the first prefix mutation. A failed
            # initialization cannot later be confused with an unrelated prefix.
            paths.save(state)
            paths.prefix.mkdir(mode=0o700)
            try:
                run(['wineboot', '--init'], env=paths.environment(), quiet=True)
                run(['wineserver', '-w'], env=paths.environment(), quiet=True)
                run(['wine', 'reg', 'add', r'HKCU\Software\Wine\Explorer', '/v', 'ShowSystray',
                     '/t', 'REG_DWORD', '/d', '0', '/f'], env=paths.environment(), quiet=True)
                run(['wineserver', '-w'], env=paths.environment(), quiet=True)
                app.rename(paths.app_dir)
                shutil.copyfile(stage / 'icon.png', paths.data / 'icon.png')
                copy_runtime(paths, shim)
            except BaseException:
                run(['wineserver', '-k'], env=paths.environment(), quiet=True, check=False)
                raise
        state.update(prepared=True, shim_sha256=digest(shim))
        paths.save(state)
        if not no_integrate:
            install_integration(paths, state)
