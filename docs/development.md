# Development and release review

## Layout

```text
bin/spark-omarchy       CLI entry point (source/package)
bin/build-shim          Windows x64 DLL build
bin/test                Python tests and syntax checks
bin/test-native         API regression tests in a disposable prefix
src/spkenv.c            Original compatibility shim source
src/spkenv.def          Two API exports / USERENV forwarding
spark_omarchy/          Standard-library-only setup, patch, icon and lifecycle code
manifest.json           Reviewed vendor URL/version and whole-file hashes
PKGBUILD                Optional local Arch integration package
```

This is an existing Windows application's integration layer, not a new Qt app.
It does not modify Omarchy source or replace system Wine. A GUI installer would
add dependencies without making the underlying compatibility more reliable.

## Build the shim

Preferred on Arch/Omarchy:

```bash
omarchy pkg add clang binutils wine
./bin/build-shim
```

Clang targets Windows x64 using Wine's installed Windows/MSVCRT headers. Host
GNU ld links Wine's PE import libraries. `-fasynchronous-unwind-tables` produces
Windows unwind metadata; the build refuses output without `.pdata`. This is a
real PE DLL, not the first experiment's ELF/Winelib bridge.

Overrides for nonstandard installations:

```bash
CLANG=/path/to/clang \
WINE_INCLUDE_DIR=/path/to/wine-headers \
WINE_LIB_DIR=/path/to/x86_64-windows \
  ./bin/build-shim /path/to/output-directory
```

`WINE_INCLUDE_DIR` must contain `windows/` and `msvcrt/`. The usual Arch defaults
are `/usr/include/wine` and `/usr/lib/wine/x86_64-windows`.

Alternatively, `x86_64-w64-mingw32-gcc` on PATH is used automatically. The MinGW
build links only Kernel32/Shell32 and does not bundle a C++ runtime. CI uses this
route. No vendor DLL is copied into the repository or build artifacts.

## Tests

```bash
./bin/test
./bin/test-native
```

The Python tests use synthetic PE/icon fixtures and fake OAuth values. They test
protocol allowlisting, argument preservation, no shell/logging flags, XDG paths,
unit/desktop generation, patch hash guards, icon transparency/orientation and
selective rollback. They do not authenticate or inspect a live mailbox.

The native test validates the shim's null/size/error contracts and the forwarded
API in a **fresh temporary Wine prefix**. It suppresses Mono/Gecko prompts and
cleans up only that owned temporary prefix. It requires a graphical display (or
`xvfb-run` on headless CI), Wine, and either `winegcc` or MinGW GCC. It does not
execute Spark or reuse your default/signed-in prefix.

The published GitHub Actions workflow builds and runs these tests on push and
pull requests. A green workflow does **not** prove provider login, mail sync,
battery life or every desktop behavior. Check the actual result before claiming
it passed. Compiled-shim artifacts are our own code, not the proprietary app.

## Fresh installation test without changing your desktop defaults

Use a directory outside tracked files and supply your own verified installer:

```bash
XDG_DATA_HOME="$PWD/build/manual/data" \
XDG_CONFIG_HOME="$PWD/build/manual/config" \
XDG_CACHE_HOME="$PWD/build/manual/cache" \
  ./bin/spark-omarchy install --accept-vendor-terms --no-integrate \
  --installer /path/to/the/reviewed/Spark.exe
```

This still executes Wine to initialize its new prefix; it is not a security
sandbox. It does not write Linux desktop handlers/units. Do not then run
`repair` against your real session bus and assume custom XDG paths are isolated
from that manager's search path. For complete integration/uninstall testing,
use mocked system tools, a disposable desktop account or a dedicated test VM.

Do not migrate, reset or commit a real prefix as a test fixture. Native code
sampling can require pausing threads: obtain permission and never upload memory
or crash dumps. Public reports should contain metadata and sanitized stacks,
not raw application logs.

## Reviewing a new Spark version

1. Obtain the installer **directly from the vendor** and record its version/URL.
2. Compute its SHA-256 locally. A hash from this repo pins identity, not independent
   vendor authenticity; use authenticated vendor transport and review the source.
3. Extract to a disposable staging directory. Inspect the new Foundation imports,
   the failing API contract and the call path. Do not assume the same bug/patch.
4. Compute the original and reviewed patched whole-file hashes. Never implement
   a generic `--skip-checksum` or force unknown imports to fit.
5. Verify the native shim build, its exports and unwind metadata. Run regression
   tests and add tests for any newly supported layout/behavior.
6. Test a fresh prefix: startup beyond the old crash point, Google OAuth delivery,
   real inbox behavior if authorized, normal close, no orphan helpers, native icon
   and no unexpected resource cap. Test an existing install separately; never
   substitute it for a clean install.
7. Qualify the NODE_CONFIG updater-control flag, compute executable/app archive
   hashes too, and add the reviewed release to `updates/catalog.json`. Set its
   minimum client and shim ABI, then sign locally with a new sequence as described
   in [approved updates](updates.md). Update bootstrap pins only deliberately.
   Document every unverified capability and any migration path.
8. Review legal/distribution boundaries: only our source/DLL ships. The installer,
   modified Foundation, icon, account data, logs and dumps must remain local.

The update CLI accepts only signed approved version changes. Automatic activity
stops at verified download; explicit application requires a stopped prefix,
confirmation, an offline snapshot and a journaled/versioned switch. Unfinished
transactions block managed starts. Rollback is allowed only before first launch;
post-launch data migrations require deliberate manual recovery, not an old-EXE
swap. Do not weaken those guards to accept an unreviewed installer.

## Publishing

Review `git diff --cached` and the complete tracked file list. No local paths,
usernames, provider IDs tied to a person, tokens, mail, screenshots of accounts,
vendor binaries or icons should be included. The Google callback application's
public client identifier is protocol configuration, not a client secret.

Only after tests pass, create a version tag/release and attach artifacts built
from that exact source. The workflow tests/builds on push and PR; it does not
automatically create a release or publish to AUR/Omarchy repos.
A future public package submission needs its own review and user authorization.
