# Troubleshooting

Start with:

```bash
spark-omarchy doctor
spark-omarchy status
```

`doctor` checks tool availability, version/patch integrity, icon, service state,
CPU-quota metadata and OAuth defaults. It does not read mail, cookies, auth URLs,
application logs or dumps. A stopped app is not inherently a failed installation.
For a bug report, review even this metadata before sharing it publicly.

## OAuth redirect does not return to Spark

1. Keep **this installation's** Spark instance running.
2. Run `spark-omarchy repair`, then check `doctor` for `oauth_handlers`.
3. Start a **new** Google/provider sign-in inside Spark. Old auth sessions/codes
   may have expired or been canceled.
4. Allow the browser to open **Spark Mail OAuth Bridge**. A previously denied
   external-protocol prompt may need revisiting in your browser settings.
5. Ensure another Spark prefix/installation is not receiving the scheme instead.

The bridge routes only six reviewed OAuth schemes; it does not take over HTTP,
HTTPS or mailto. Microsoft/Yahoo routing exists but those providers' complete
flows have not been qualified here. If the browser uses a different callback
scheme, report **only its scheme name** (before `:`), the provider and the visible
error. Do not paste the URL, query, fragment, code, state or tokens.

A callback delivered while Spark is closed is deliberately rejected: open Spark
and begin a fresh sign-in. `open-url` is an internal entry point, not a debugging
command for experimenting with real auth URLs.

## Closing the window does not quit

Disable **Settings → General → Close application to tray** in Spark. Hiding
Wine's tray is not the same thing as changing this application preference.

A normal quit can take several seconds while Spark saves/shuts down. Check
`spark-omarchy status` after that. The service cleans remaining Wine helpers when
the main app exits; it should not stay syncing indefinitely after a normal quit.

If it is stuck, the explicit stop command affects only this project's prefix:

```bash
spark-omarchy stop
```

This can interrupt in-flight sync or unsaved work. Prefer normal close. Never use
an unqualified `wineserver -k`: that can kill an unrelated default prefix.

## Phantom upper-left window

Wine can create a tiny standalone `explorer.exe` system-tray window. Installation
sets `HKCU\Software\Wine\Explorer` DWORD `ShowSystray=0` **inside this prefix**.
Fully stop and restart Spark after changing it. If the window belongs to another
Wine installation, this project's setting cannot and should not hide it.

Inspect window ownership with Hyprland if necessary, but do not hide every Wine
window with a compositor rule: that could hide sign-in/error dialogs too.

## CPU, fans and responsiveness

The default is **uncapped**. A 75%-of-one-core quota was tried locally and made
Spark crawl. Removing it improved responsiveness. Do not reintroduce that limit
as a claimed fix, and remember that 75% in systemd CPUQuota means less than one
logical core—not 75% of the whole machine.

- First determine whether this is initial sync/indexing or persistent idle load.
- Use normal quit when not using Spark; verify `status` becomes `stopped`.
- Inspect worker CPU before changing GPU settings. Our observed hotspot was the
  mail-engine utility process, not primarily the renderer/GPU process.
- Do not swap C++/UCRT libraries indiscriminately; those experiments did not fix
  the diagnosed startup crash.
- Extra quotas may come from your own parent cgroups or overrides. `doctor`
  checks this project's slice, not every ancestor constraint.

High ongoing CPU and hundreds of threads remain an open compatibility/performance
question. Prefer a provider web UI or native Linux client if this setup is too
costly for your laptop. No battery-life or quiet-fan guarantee is made.

## Checksum mismatch or vendor files changed

Stop. The tool intentionally rejects unexpected installers or Foundation DLLs.

- Use the exact vendor build in `manifest.json`, not an arbitrary current download.
- Do not edit the expected hash to accept a different version without reviewing
  its imports, behavior and patch result.
- Do not download a replacement from an untrusted third-party archive.
- Do not apply the old patch blindly after accepting an in-app update.

A changed app may need a new compatibility release. There is no automatic app
upgrade path yet. Keep account data and the state record intact while diagnosing.
See [development](development.md#reviewing-a-new-spark-version).

## Interrupted preparation

The state may say `prepared: false`. This is deliberate: successful installation
is not claimed after a prefix-initialization error. Fix the missing prerequisite
or environment problem first. If it was a new, unused test install, you can run
the repository/package CLI:

```bash
./bin/spark-omarchy uninstall --yes --purge-data
```

**That permanently deletes the managed prefix and its data.** Use it only when
you know there is nothing you need in that installation. Normal uninstall retains
data and will not make an incomplete prefix magically valid. For data-bearing
installs, preserve an offline copy and investigate rather than deleting state.

Do not follow generic instructions to delete `~/.wine`: this project does not
use the default Wine prefix.

## Launcher, icon or missing permissions

- Close and reopen the app launcher after installation.
- Run `spark-omarchy repair` and check that the desktop database was updated.
- `~/.local/bin` must be in your shell's PATH; use its absolute command path if not.
- The icon is extracted from the reviewed executable. It is not committed in Git;
  it will appear only after successful preparation/integration.
- Run setup as the logged-in desktop user. A root shell has the wrong home,
  session bus, desktop defaults and ownership.
- On Omarchy, use `omarchy pkg add ...` in an interactive terminal if sudo needs
  your password. Never paste a password/token into this project's diagnostics.

## Service will not start

Confirm a graphical session and `systemctl --user` availability. Custom XDG paths
must be present in the systemd user manager's configuration search path, not just
in the installer's shell. A headless SSH session does not necessarily have the
Wayland/X11/session environment needed to display an app.

Avoid posting `systemctl status` or journal output unreviewed: transient OAuth
unit metadata can include callback arguments. The project's own `doctor` filters
its queries to specific safe metadata. No remote debugging endpoint is enabled
by default. If you enable one for local development, bind only to loopback and
remove it immediately afterward; it can expose authenticated application state.
