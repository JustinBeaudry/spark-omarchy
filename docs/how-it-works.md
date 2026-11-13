# How it works

## Architecture

```text
Omarchy launcher ── spark-omarchy start ── systemd user service ── Wine ── Spark
Browser callback ── hidden OAuth desktop handler ── open-url ── second instance
                                                                          │
                                    Spark --win-open-url -- <URL> ──────────┘

Spark Foundation.dll ── spkenv.dll ── SHGetFolderPathW(CSIDL_COMMON_APPDATA)
                              └──── GetProfilesDirectoryW forwarded to USERENV
```

The app and its helper processes live in a dedicated Wine prefix and systemd
slice. The slice groups processes for lifecycle management, **not throttling**.
There is no CPU quota and no automatic background start at login. Wine prefixes
separate Windows configuration, not filesystem/network access or trust.

## Confirmed startup failure

Tested Spark: `3.32.4.141552`; tested Wine: `11.20`.

1. A systemd core dump was not available: Spark's Windows child crash was
   captured by its own Crashpad handler.
2. Spark's mail worker exited with `0xc0000005`, and its main process then
   deliberately quit. The welcome window could appear before this failure.
3. The original fault appeared in Wine's UCRT. Microsoft C++ redist installation
   and native-UCRT experiments did not fix it.
4. WineDbg unwound a later dump through `vcruntime140`, `Foundation`,
   `RDCalendarsAPI` and `dispatch`. The copy length was `0x1fffffffe`.
5. Import-table lookup and disassembly identified the caller:
   Foundation IAT RVA `0x41d1b8` imports `GetAllUsersProfileDirectoryW`.
   Code around RVA `0x3857b4–0x3857e8` calls it twice without checking failure,
   decrements the returned zero DWORD and constructs a UTF-16 string of
   `0xffffffff` characters. Twice that length is nearly 8 GiB.
6. Wine's tagged source confirms that this API is a stub returning `FALSE`
   without filling the buffer length in that version.

The important point is **invalid caller input**, not a broken memory-copy
implementation. Replacing the runtime changed the faulting implementation but
not the oversized request.

Sources:

- [Wine 11.20 USERENV source](https://github.com/wine-mirror/wine/blob/wine-11.20/dlls/userenv/userenv_main.c)
- [Microsoft GetAllUsersProfileDirectoryW contract](https://learn.microsoft.com/en-us/windows/win32/api/userenv/nf-userenv-getallusersprofiledirectoryw)
- [Microsoft SHGetFolderPathW documentation](https://learn.microsoft.com/en-us/windows/win32/api/shlobj_core/nf-shlobj_core-shgetfolderpathw)
- [Spark's official download page](https://sparkmailapp.com/download)

No crash dumps or original diagnostic logs are published here: they can contain
account data. The reproducible implementation evidence is the reviewed hashes,
import checks, own-source shim and synthetic regression tests.

## Patch boundary

The installer extracts the reviewed NSIS payload rather than executing its
PowerShell-dependent setup logic. It keeps an original Foundation backup beside
the modified file, then replaces the single import-name string
`USERENV.dll\0` with `spkenv.dll\0\0`. Length and import-table shape are preserved.

Both whole-file checksums are verified, and unknown layouts/builds are refused.
No fixed byte offset is trusted by the patcher. Only our source code and shim may
be redistributed under this project's license; the modified vendor copy stays
on the installing user's machine. Modifying it invalidates its vendor signature.

`spkenv.dll` implements proper null-pointer, required-size, insufficient-buffer
and terminating-NUL behavior. It locates common app data dynamically rather than
hardcoding a username or a `ProgramData` path. The second import is forwarded to
Wine's USERENV. A proper upstream Wine implementation would eventually be cleaner
than an app-local shim; it has not been submitted or validated here.

## OAuth boundary

Spark registers custom protocols in its Windows registry. The Linux browser
cannot see that registry. A hidden desktop entry registers only the six known
OAuth schemes from the reviewed build. It forwards the unchanged callback as one
argument, without shell interpretation, to Spark's existing instance using:

```text
Spark Desktop.exe --win-open-url -- <callback>
```

The callback bridge rejects unknown schemes/control characters/oversized inputs.
It does not inspect or manufacture OAuth codes, states, tokens or cookies. It
requires Spark to be running: a stale callback cannot restore a lost OAuth
session. The transient forwarding unit has a generic random name and discards
stdout/stderr. The URL is necessarily present in the receiving process's argv
and transient service metadata while being delivered; other code running as the
same user is within the same trust boundary. This is not protection against a
compromised desktop account.

Previous scheme handlers are recorded before registration. Uninstall restores
one only if ours is still selected, preserving later user changes. Browser and
`mailto` defaults are not taken over. Account sign-in still occurs in Spark or
the provider's browser page.

## Desktop behavior and icon

The prefix-only `HKCU\Software\Wine\Explorer` DWORD `ShowSystray=0` hides Wine's
standalone tray window. This does not change Spark's own close-to-tray preference:
turn that off in **Settings → General**. On normal close, Spark performs its own
shutdown; after the main process exits, systemd's stop action kills remaining
helpers in this project's dedicated prefix. An explicit `stop` command can stop
that prefix without waiting for the normal UI save sequence.

Spark's first group-icon resources contain 32-bit Windows DIB images. Installation
extracts the largest entry, converts BGRA/mask data to RGBA PNG with Python's
standard library, and installs it in the user's hicolor icon theme as
`spark-omarchy`. No branded icon is committed or downloaded from an unrelated site.
The window matches `StartupWMClass=spark desktop.exe`.
