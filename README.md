# Spark Mail on Omarchy

**An unofficial, experimental way to run Spark Desktop on an x86_64 Omarchy desktop.**

Spark provides the application. This project provides a small Wine compatibility
shim, a Google/OAuth callback bridge, a managed launcher, and a locally extracted
Spark icon. It does **not** turn Spark into a native Linux application.

> **Early release, not a compatibility guarantee.** Startup and Google sign-in
> worked during local testing. Complete synchronization, attachments,
> notifications and long-term reliability have not been qualified. Use a
> browser/provider fallback for important mail. Neither Spark/Readdle nor Omarchy
> endorses this project.

## What you get

- **Spark Mail in the app launcher**, with Spark's own icon extracted on your
  machine from its official executable—not a generic Wine icon.
- A targeted workaround for the SparkCore startup crash on **Wine 11.20**.
- Browser-to-app OAuth callbacks, including Google's callback scheme.
- An isolated **configuration prefix**, not a security sandbox.
- No system Wine patch, no VM, no automatic login startup, and **no hard CPU cap**.
- Diagnostics that do not collect mail, cookies, callback URLs or crash dumps.
- Uninstall that preserves account data by default and selectively restores
  previous OAuth handlers.

**Pinned application:** Spark Desktop `3.32.4.141552` (Windows x64).
Only this reviewed build is accepted. The installer and original/patched
Foundation DLL have pinned SHA-256 checksums in [`manifest.json`](manifest.json).
A newer Spark version is **not** assumed compatible.

## Quick start

### 1. Install prerequisites

On Omarchy, run in an interactive terminal:

```bash
omarchy pkg add wine 7zip python curl desktop-file-utils clang binutils
```

`clang` and `binutils` build our small DLL; they are not needed at runtime after
installation. This avoids installing the much larger MinGW GCC toolchain on your
machine. The alternative MinGW build is supported for developers and CI.

You need x86_64, a graphical session, an available systemd user manager, a working
browser, and several GiB of free disk space. This is lighter than a Windows VM,
**not** a lightweight native mail client. Initial syncing can use substantial
CPU/RAM. See [requirements and compatibility](docs/compatibility.md).

### 2. Clone and install as your desktop user

```bash
git clone https://github.com/JustinBeaudry/spark-omarchy.git
cd spark-omarchy

# Read the code and the vendor policies before running the installer.
./bin/spark-omarchy install --accept-vendor-terms
```

Do **not** run the installer with `sudo`. It downloads Spark directly from the
vendor, checks its checksum, builds our shim, and prepares a new per-user prefix.
It never adopts or resets another Wine prefix. Existing prototype installations
are left alone.

`--accept-vendor-terms` confirms that you reviewed Spark's
[terms](https://sparkmailapp.com/legal/terms) and
[app privacy policy](https://sparkmailapp.com/legal/privacy-app). It is not a license
provided by this project. Vendor policies and account requirements still apply.
No Spark executable, modified vendor DLL, icon or personal data is distributed
in this repository.

Already have the **exact pinned** vendor installer?

```bash
./bin/spark-omarchy install --accept-vendor-terms --installer /path/to/Spark.exe
```

Its checksum is still checked. There is intentionally no `--skip-checksum` switch.

### 3. Open Spark and complete two important setup steps

Open **Spark Mail** from Omarchy's app launcher, or run:

```bash
~/.local/bin/spark-omarchy start
```

1. Sign in normally. When the browser asks to open **Spark Mail OAuth Bridge**,
   allow it. Start a fresh sign-in rather than reusing an expired browser tab.
   **Never paste the callback URL into a bug report or chat.**
2. In **Settings → General**, turn **Close application to tray** **off**.
   This is Spark's own setting, not something we silently change in its database.
   Without it, closing the window can leave Spark syncing in the background.

The standalone Wine tray is hidden in this prefix. Normal window close should
let Spark save state and quit; shutdown can take several seconds. The managed
service then cleans up leftover helpers. There is no remote-debugging port in the
installed service.

For the full installation model and an optional Arch package, see
[installation](docs/installation.md).

## Everyday commands

| Command | Purpose |
| --- | --- |
| `spark-omarchy start` | Start Spark, or bring its existing instance back |
| `spark-omarchy status` | Report whether the managed app is running |
| `spark-omarchy doctor` | Check prerequisites, reviewed patch and desktop integration |
| `spark-omarchy doctor --json` | Machine-readable metadata checks; no mail/log collection |
| `spark-omarchy repair` | Recreate owned launcher/units and register OAuth handlers |
| `spark-omarchy stop` | Stop the whole dedicated prefix; prefer normal close for saving state |
| `spark-omarchy uninstall --yes` | Remove integration; keep account data |

Use `~/.local/bin/spark-omarchy` if your terminal has not yet picked up
`~/.local/bin` in `PATH`. Nothing needs to be enabled at login.

## Why a shim is necessary

In the tested Wine build, `GetAllUsersProfileDirectoryW` returns failure without
setting the requested buffer length. Spark's bundled Foundation library fails to
check that result, subtracts one from zero, and attempts an approximately **8 GiB
string copy**. The mail worker crashes; Spark then quits.

Our DLL implements that API using the Windows common-appdata folder API and
forwards the other imported USERENV function to Wine. Installation changes only
the USERENV import name in a **local copy** of the reviewed Foundation DLL. It
retains the original file and verifies both input and output hashes.

**This invalidates the modified vendor DLL's signature.** It is a narrow
compatibility workaround, not an official or signed Spark build. We do not patch
login checks, TLS, account entitlements or authorization. See the
[technical explanation](docs/how-it-works.md) and [security model](SECURITY.md).

## What we learned—and deliberately do not do

- A welcome screen is not proof of working mail. The worker originally crashed
  a few seconds later. Read the [test matrix](docs/compatibility.md).
- Installing Visual C++ runtimes or replacing UCRT did **not** fix that crash.
  This setup does not install those experimental replacements.
- Linux needs its own OAuth handlers even when they are registered inside Wine.
  Spark expects `--win-open-url -- <URL>`, not a bare URL.
- Spark's default close-to-tray behavior is different from quitting.
- A **75%-of-one-core CPU cap made the interface crawl**. It was removed, and
  responsiveness improved. This package has no CPU quota or reduced nice priority.
- High CPU may be initial sync/indexing or a remaining compatibility issue;
  we have not established which. Do not call thermal throttling a fix.
- **Do not update Spark from inside the app and assume the patch survives.**
  New vendor builds need separate review and checksums. This project currently
  has no automatic application upgrade path.

## Troubleshooting

Start with `spark-omarchy doctor`, then see the focused guide:

- [Browser finishes authentication but Spark does not receive it](docs/troubleshooting.md#oauth-redirect-does-not-return-to-spark)
- [Closing the window leaves Spark running](docs/troubleshooting.md#closing-the-window-does-not-quit)
- [High CPU, fans or a slow interface](docs/troubleshooting.md#cpu-fans-and-responsiveness)
- [Unsupported build, changed files or interrupted setup](docs/troubleshooting.md#checksum-mismatch-or-vendor-files-changed)
- [Remove integration or permanently erase its data](docs/uninstall.md)

Before filing an issue, remove names, addresses, account identifiers, paths you
do not want public, and any authentication material. Do **not** attach raw Spark
logs, a Wine prefix or crash dumps. [Report a problem safely](CONTRIBUTING.md).

## Development and packaging

```bash
./bin/test          # Python regression tests; no vendor downloads or login
./bin/build-shim    # Real Windows x64 DLL, with unwind metadata
./bin/test-native   # API tests in a fresh, disposable Wine prefix
```

See [development](docs/development.md) for build details, CI scope, updating the
pinned version and testing installation/uninstall in an isolated environment.
**CI publication is pending the owner's GitHub workflow authorization.** Local
regression/native tests passed; no remote CI pass is claimed yet.
A local [`PKGBUILD`](PKGBUILD) is provided for Arch users; **this is not an AUR or
official Omarchy repository package**. It packages only this project's integration
code and shim. Spark is downloaded separately, as your user, after installation.

## License and attribution

The integration code and documentation are [MIT licensed](LICENSE). Spark and its
paper-plane icon remain the property of their respective owners and are used
locally from the vendor-provided app. Wine and build tools have their own
licenses. This project grants no rights to redistribute Spark, its modified
binaries or its trademarks.
