# Installation, ownership and recovery

## Two installation choices

### Per-user source install (recommended for trying it)

Follow the README prerequisites, clone the repo and run:

```bash
./bin/spark-omarchy install --accept-vendor-terms
```

The source checkout can be moved or removed afterward: a private copy of the
runtime and our compiled shim is installed in the per-user data directory.
There is no `curl | sh`, automatic sudo invocation or root-run Wine process.
The installer does not launch Spark or log you in automatically.

### Optional local Arch package

From the repo root, as a regular user:

```bash
makepkg -si
/usr/bin/spark-omarchy install --accept-vendor-terms
```

`makepkg` resolves normal build dependencies and uses package-manager elevation
when installing the package. The package contains **only our code, documentation
and compiled shim**. The second command downloads/prepares Spark as your desktop
user. This repo is not yet in the AUR or Omarchy's official package repositories;
`omarchy pkg add spark-omarchy` is not an available installation method.

The user-local entry point is intentionally independent of the system package.
Removing the Arch package alone does not erase downloaded Spark or account data.
Use the uninstaller before removing the source/package if you want the desktop
integration removed as well. For future code updates, use the new source/package
entry point explicitly to refresh the user-local runtime. Integration-code
updates are not automatic; application updates follow the separate signed,
explicit-application flow in [approved updates](updates.md).

## What installation does

1. Checks architecture, tools, vendor-terms confirmation and existing ownership.
2. Builds a Windows x64 DLL (or uses the package's already-built own-source DLL),
   requiring its exports and x64 unwind metadata.
3. Downloads the fixed vendor URL, or accepts `--installer FILE`, and verifies
   the entire installer SHA-256 before extracting any payload.
4. Extracts the pinned NSIS payload with 7-Zip instead of running its setup code.
5. Verifies the original Foundation hash and expected two imports; saves the
   original; redirects USERENV imports to `spkenv.dll`; verifies the output hash.
6. Extracts Spark's icon from the vendor executable and converts it locally to PNG.
7. Initializes a new dedicated prefix, disables the generic Wine tray, and copies
   the prepared app into it. Wine Mono/Gecko prompts are suppressed because this
   Electron app does not require those components for the tested workaround.
8. Saves a private ownership/rollback record and a standalone runtime copy.
9. Installs user desktop entries and systemd units; records existing scheme
   handlers before registering only Spark's six known OAuth callbacks.

No provider login or desktop secret is requested by the installer. Read the
vendor policies separately before using `--accept-vendor-terms`.

## Files and defaults

Paths below honor `XDG_DATA_HOME`, `XDG_CONFIG_HOME` and `XDG_CACHE_HOME` when set
to absolute paths. `~/.local/bin` remains the launcher location.

| Default path | Contents |
| --- | --- |
| `~/.local/share/spark-omarchy/prefix/` | Dedicated Wine prefix, Spark, accounts, mail/cache data |
| `~/.local/share/spark-omarchy/runtime/` | This project's standalone Python runtime and own shim |
| `~/.local/share/spark-omarchy/state.json` | Private version/ownership/previous-handler record |
| `~/.local/share/spark-omarchy/backups/` | MIME snapshots and private offline prefix snapshots for approved updates |
| `~/.local/share/spark-omarchy/versions/` | Retained versioned application files, not account data |
| `~/.local/share/spark-omarchy/update-state.json` | Catalog sequence, checks and notification deduplication |
| `~/.local/share/spark-omarchy/pending-update.json` | Signed approval envelope for a downloaded update |
| `~/.local/share/spark-omarchy/icon.png` | Locally extracted vendor icon |
| `~/.local/share/icons/hicolor/256x256/apps/spark-omarchy.png` | Launcher icon |
| `~/.local/share/applications/spark-omarchy.desktop` | Visible Spark Mail launcher |
| `~/.local/share/applications/spark-omarchy-oauth.desktop` | Hidden callback handler |
| `~/.config/systemd/user/spark-omarchy.service` | Managed app process/lifecycle |
| `~/.config/systemd/user/spark-omarchy.slice` | Process grouping; **no hard CPU limit** |
| `~/.config/systemd/user/spark-omarchy-update.service` | Checks/downloads only; no application step |
| `~/.config/systemd/user/spark-omarchy-update.timer` | Daily checks, disabled until explicit opt-in |
| `~/.local/bin/spark-omarchy` | User-local command |
| `~/.cache/spark-omarchy/` | Reviewed vendor installer download |

Account state is never copied into the source tree. State is written atomically
with mode 0600. Fresh managed data/prefix directories use mode 0700. Generated
integration files are user-owned; system Wine and `/usr/share/omarchy` are untouched.
Default browser and `mailto` are not changed. Spark never starts at login.
The update-check timer is installed but disabled until explicitly opted in.
The native background updater is disabled through the reviewed NODE_CONFIG flag;
no private app-setting database or vendor archive is edited for that control.

## Repeat installation and repair

Running `install` again for an intact reviewed installation refreshes our runtime
and repairs owned integration rather than replacing account data. Approved
installed application manifests are retained independently of the bootstrap pin.
`repair` refreshes our runtime/shim resources and restores owned files/registrations
without rebuilding or replacing the vendor application. An unrelated prefix,
launcher, symlink or unexpected patch is refused.

An interrupted integration can leave some handlers/files installed. Previous
handler information is saved **before** those changes, so rerunning install or
repair can finish. Do not delete the state file to suppress ownership checks.
If initialization itself failed, the record remains `prepared: false` rather
than claiming success. Use the recovery guidance in troubleshooting.

`--no-integrate` prepares a new app/prefix only, without writing launchers,
units or Linux protocol defaults. It is useful for isolated testing. Complete
integration later with `repair` from the same source or package command.

## Existing experimental installations

The original lab prefix and service used different names. This installer never
adopts them or migrates login data automatically. Keep them intact while testing
the new package. If you install alongside them, the new OAuth handler becomes
the default for its supported schemes; only use **one** Spark instance when
signing in, so the callback reaches the intended prefix. Uninstall can restore
the prior handler when it is still ours.

Do not copy a running Wine prefix, publish it, or reset it just to obtain the new
launcher. Migration of existing account data has not been qualified. A fresh
login to the new prefix is the conservative path; retain the old data until you
have verified what you need.
