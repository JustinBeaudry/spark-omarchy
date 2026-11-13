# Changelog

## 0.1.0 — experimental first release

- Added a per-user installer for the reviewed Spark Desktop `3.32.4.141552` build,
  with installer/input/output checksum guards and retained original Foundation.
- Rebuilt the USERENV compatibility shim as a real Windows x64 DLL with unwind
  metadata; added native API-contract regression tests.
- Added six allowlisted OAuth callback schemes and exact `--win-open-url --`
  forwarding without shell interpretation or callback output logging.
- Added a managed desktop launcher/service, no hard CPU cap or lowered nice
  priority, prefix-only tray hiding and instructions for Spark's quit-on-close setting.
- Extract Spark's launcher icon locally from the vendor executable; no vendor
  binary or icon is redistributed.
- Added metadata-only diagnostics, selective handler restoration, data-preserving
  uninstall and an explicit guarded purge.
- Added source/package installation docs, troubleshooting, security guidance,
  development instructions, local PKGBUILD and GitHub Actions regression/native CI.

Local verification includes a clean-prefix startup test, native shim API tests,
Python regression tests and local Arch package creation. Google sign-in was
user-confirmed on the original experiment, not automated or qualified with every
provider in the new installer. Full mail sync and long-term reliability remain
unverified. In-app application upgrades are not supported.
