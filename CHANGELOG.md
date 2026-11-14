# Changelog

## 0.2.0 — approved-update checks and downloads

- Added an Ed25519-signed, expiring stable catalog, monotonic sequence/equivocation
  checks, artifact pins, minimum client and shim-ABI gates. The initial catalog
  still approves only the already-reviewed bootstrap Spark version.
- Added opt-in daily checks and verified downloads with deduplicated notifications;
  background mode can never apply, stop Spark, or run a vendor app.
- Added explicit closed-prefix application with private offline snapshots,
  versioned app storage, journaled migration, atomic pointer switching and crash
  recovery. Rollback is allowed only before first launch; data migrations are not
  automatically reversed after launch.
- Disabled Spark's normal background updater using its existing NODE_CONFIG flag;
  verified that flag in a fresh-prefix main-process runtime test. Its manual
  update menu remains unsupported and must not be used for managed updates.
- Added service pre-start guards, update-state-aware diagnostics, timer uninstall
  cleanup, signing tooling, failure/recovery tests and an update/security guide.
- Integration-code/shim updates remain explicit source/package upgrades. No new
  vendor version or real mailbox migration is claimed qualified by this release.

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
