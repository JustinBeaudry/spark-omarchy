# Requirements and compatibility

## Supported installation target

- x86_64 Omarchy / Arch Linux with Wine and a graphical session.
- A working systemd **user** manager and `~/.local/bin` available to your shell.
- XDG desktop integration (`xdg-mime`, `update-desktop-database`).
- A browser able to launch registered custom protocols.
- The exact Spark build in `manifest.json`; currently `3.32.4.141552`.

The manual experiment used Wine `11.20-1`. Other Wine builds may work, fail
differently, or implement the missing API themselves. The shim is not proof of
compatibility with every release. ARM, macOS, non-systemd distributions and
Flatpak/Bottles prefixes are not supported by this installer.

## Evidence matrix

| Capability | Evidence / limitation |
| --- | --- |
| Original crash reproduced | SparkCore access violation after welcome screen |
| Crash mechanism identified | Tagged Wine source, disassembly, exception registers and WineDbg stack |
| Shim buffer contract | Native C tests in a fresh disposable prefix |
| Fresh source installer | Official pinned payload extracted/patched; clean-prefix startup exercised locally |
| Google account login | User-confirmed on the original experimental setup |
| Linux OAuth routing | Registered custom schemes and required argument forwarding verified; synthetic regression tests |
| Spark launcher icon | Vendor Windows icon extracted locally and converted to 256×256 PNG |
| Quit-on-close | User setting disabled; normal close reached clean service exit and zero prefix processes in a local test |
| Hard CPU cap | Tried at 75% of one core, rejected because the UI crawled; **not enabled** |
| Full mailbox sync / daily reliability | Not qualified |
| Attachments / printing / notifications | Not qualified |
| Microsoft/Yahoo account login | Schemes routed, provider-specific sign-in not manually qualified |
| New Spark versions / in-app updater | Not supported without fresh review |
| CI on GitHub | See actual workflow results; do not infer mail functionality from unit tests |

Do not conflate the original signed-in prototype with the newly packaged
installer: the latter gets a new prefix and was tested for clean startup, not
with anyone's real account in CI. Regression tests never authenticate to a
provider or download mail.

## Resources

Allow **several GiB** of free disk space for Wine, the extracted application,
installer cache and temporary preparation. The Windows installer is about 219 MiB;
that is not the installed footprint. Source building also needs Clang and its
installed dependencies. Application cache/mail storage grows with use.

The mail worker was observed using nearly two logical cores and hundreds of
threads. One early sample had a CPU package around 93°C. A hard 0.75-core cap
lowered load but made the app unpleasantly slow; removing it improved user-reported
responsiveness. Those observations are not a universal temperature or battery
benchmark. Mail sync/indexing versus Wine overhead has not been isolated.

This package therefore avoids hard quotas and reduced process nice priority.
If load stays high **after** initial sync, profile the worker rather than
assuming that disabling GPU acceleration or swapping runtimes will fix it.

## Version policy

The pin is a compatibility/security boundary, not a recommendation to remain on
an old mail client indefinitely. If the vendor stops serving it, a vulnerability
requires an update, or a login policy blocks it, stop and review a newer build.
Do not obtain an old installer from an untrusted mirror or bypass the hash check.
We do not know of a relevant vendor vulnerability in this build; nor do we claim
that it is currently supported or secure merely because it launches.
