# Uninstall and rollback

## Keep your account data (default)

Close Spark normally, wait for it to quit, then:

```bash
spark-omarchy uninstall --yes
```

This stops the dedicated managed service, disables/stops update checks, removes
this project's launcher/icon/user units, and restores previous OAuth handlers **only where ours is still
selected**. It surgically removes its own associations rather than overwriting
your entire `mimeapps.list`, so later browser/app choices are preserved.

It retains the prefix, mail/account data, runtime, ownership record, retained
application versions, offline update snapshots and installer cache. No unrelated Wine prefix or system package is removed. If the user-local
command was removed, use the repository's `./bin/spark-omarchy` or the package's
`/usr/bin/spark-omarchy` for later recovery/reinstallation.

Reinstalling the same reviewed version can restore integration around an intact
managed app. It does not promise recovery from an incomplete prefix or a vendor
in-app update.

## Permanently remove the account data too

**This is destructive and cannot be undone by this project.** It deletes this
installation's entire managed data directory, including the Wine prefix,
credentials/session state, caches, retained versions, offline update backups
and any locally stored mail or unsynced work.
Only do this after closing Spark and verifying that you have what you need.

```bash
spark-omarchy uninstall --yes --purge-data
```

The two explicit flags are intentional. The tool checks the managed-state marker
and refuses symlinked prefix/data paths. It does not discover or delete other
Spark installations. The standalone download cache remains at
`${XDG_CACHE_HOME:-$HOME/.cache}/spark-omarchy`; inspect and remove it yourself if
you want the vendor installer download gone as well.

If you installed the optional Arch package, remove it separately after the
per-user uninstall, for example via Omarchy's package removal UI. Removing the
package by itself is not a request to delete personal data.

## Roll back only the compatibility patch

Stop Spark first. The prepared app keeps:

```text
prefix/drive_c/SparkOmarchy/resources/app.asar.unpacked/node_modules/
  @readdle/sparkcore-win/bin/Release/SparkCore.bundle/
    Foundation.dll.spark-omarchy-original
```

Copying that file back to `Foundation.dll` removes our local import redirection,
but will restore the original crash on affected Wine versions. The launcher
checks the reviewed patched checksum and will refuse to start an unreviewed
variant. Treat this as a development rollback, not a working alternative install.
Do not delete an account-bearing prefix to undo one DLL patch.

## Restore the standalone Wine tray

Its original `ShowSystray` value was absent in the fresh prefix. To restore the
Wine default, with Spark stopped:

```bash
WINEPREFIX="${XDG_DATA_HOME:-$HOME/.local/share}/spark-omarchy/prefix" \
  wine reg delete 'HKCU\Software\Wine\Explorer' /v ShowSystray /f
```

Restart that prefix afterward. Spark's **Close application to tray** preference
is a separate setting in its own General settings.

## Backup policy

Never copy a running prefix and assume it is a consistent backup. Exit Spark,
verify it is stopped, then make your own private offline backup if desired.
Prefixes, dumps and logs can contain secrets: do not commit or upload them.
The installer saves snapshots of pre-existing MIME association files for manual
recovery, but uninstall deliberately does not restore those wholesale.
