# Approved updates: automatic downloads, explicit installation

## The first-phase policy

**The timer checks and downloads; it never installs, quits Spark, or executes a
vendor installer/application.** Application requires an explicit command and
confirmation while the entire managed prefix is stopped.

The initial signed catalog approves **only Spark 3.32.4.141552**, the already
reviewed bootstrap build. This release adds the update mechanism; it does not
claim that any newer Spark build has been reviewed or that real mailbox upgrade
migrations have been qualified. Do not bypass approval to install an arbitrary
vendor release.

There are two independent things to update:

1. **The integration client/shim:** update your source checkout or Arch package,
   then run that new entry point's `install --accept-vendor-terms` to refresh the
   user-local runtime. Invoke `/usr/bin/spark-omarchy` explicitly for a package
   upgrade if the older user-local command shadows it. This is not a self-updating
   Python-code mechanism.
2. **Spark:** the client accepts only signed, approved application manifests. It
   can download those automatically and apply them only after confirmation.
   A release requiring a newer client or shim ABI is refused until the client is
   upgraded first.

The new mechanism applies to the `spark-omarchy` namespace, not a separately named
old lab/Bottles/default prefix. It does not migrate account data automatically.

## Everyday use

```bash
spark-omarchy update --check       # Authenticate approval metadata; no app download
spark-omarchy update --download    # Download/verify only; safe while Spark is running
spark-omarchy update              # Prompt, then back up and apply only while closed
```

`update --yes` is an explicit noninteractive application request, not the timer's
behavior. It still refuses a running/starting/stopping service or any remaining
process in the managed prefix. Updates never force-close a working mail session.
The confirmed target is checked again before applying, so a changed recommendation
cannot silently substitute a different version after the prompt.

Application requires completed update-aware desktop integration. Upgrade/reinstall
or repair with the new client first; a preparation-only prefix or older service
without the lifecycle guard is not eligible for application.

Nothing launches automatically after application. Start Spark yourself once you
are ready; the launcher and systemd pre-start guard mark the version as launched
before allowing it to run.

## Opt in to daily checks and downloads

Install `libnotify` if `notify-send` is missing (for example,
`omarchy pkg add libnotify`), then:

```bash
spark-omarchy updates enable
spark-omarchy updates status
```

The user timer checks daily, randomizes its schedule and catches missed checks
when the user manager resumes. An initial check is scheduled after activation,
subject to the randomized delay. It starts **only the downloader**, not Spark.
Downloaded-version notifications are deduplicated. Generic failure notifications
are rate-limited to one per day; run `update --check` to inspect the actionable
error. OpenSSL is required to verify approvals.

To disable automatic checks and stop a running downloader:

```bash
spark-omarchy updates disable
```

The app itself is never enabled at login. Opting in does add timer activity to
the user session; this is intentionally different from silently installing a
background updater at initial setup. Desktop notifications require the user's
normal session bus/notification environment.

## Authentication and anti-replay

The fixed HTTPS endpoint is `updates/stable.json` on this repository's public
`main` branch. It is a single envelope containing a base64 payload and a detached
**Ed25519 signature**. The public verification key is bundled in
`trust/updates.pem`; no key is taken from the downloaded envelope.

The client checks:

- a bounded envelope and 64-byte signature, verified through OpenSSL;
- signed schema/channel, validity window and strictly reviewed artifact fields;
- an increasing sequence number, rejecting older catalogs after seeing a newer
  one and rejecting different metadata reusing the same sequence;
- canonical HTTPS vendor URLs, supported bundle layout/shim ABI and minimum client;
- installer, executable, app archive and original/patched Foundation SHA-256 pins;
- installed shim identity before reusing it for the approved new version.

Catalogs expire after at most 120 days; the normal signing tool defaults to 90.
The private signing key is **not** in Git, a client install, a release artifact,
the KB, or GitHub Actions. Loss/compromise of that key requires a deliberate
trust-root/client recovery process, not accepting a replacement key from the
same untrusted feed. Expiry limits stale approvals but is not a full TUF design:
a first-time client has no prior sequence history, and the local clock matters.

SHA-256 pins identify reviewed vendor bytes, not independent proof of a vendor
signature. The vendor still supplies proprietary app code with normal access to
your user files/network. No package can make a Wine prefix a security sandbox.

## What happens during explicit application

1. Acquire the installation and launch lifecycle locks; require a stopped prefix.
2. Reauthenticate the pending catalog, freshness/sequence, confirmed target and
   downloaded installer. Refuse unknown, same-version or downgrade replacements.
3. Extract and patch inactive staged files; verify the approved hashes. Do not run
   the vendor setup program or app.
4. Check free space and copy an **offline private prefix snapshot**, preserving
   symlinks rather than following them into unrelated home directories. App files
   are excluded because versioned copies are retained separately.
5. Retain the original application under `versions/<version>/app`. The first
   conversion from an existing real app directory is journaled before moving it.
6. Atomically switch the stable `prefix/drive_c/SparkOmarchy` symlink, save the new
   installed manifest and refresh the locally extracted icon.
7. Remove the journal only after the switch/state/icon steps finish. Keep the old
   application and offline snapshot. Leave Spark closed.

The first directory-to-pointer conversion needs more than one filesystem rename;
it is **journaled/recoverable**, not falsely described as a single atomic action.
Subsequent pointer changes use atomic replacement. Staged files and offline
snapshots are flushed before publication; state, pointer and journal directory
entries are fsynced in order. Automated tests simulate process death, not physical
power cuts or storage hardware failure; durability still depends on the filesystem
and hardware honoring fsync. Managed starts refuse a pending journal. A regular error attempts recovery; a killed process/power loss leaves
an explicit recovery task rather than pretending installation succeeded.

Snapshots can contain credentials, mail and unsynced state. They are owner-private,
kept locally, and are not automatically uploaded or deleted. Allow enough disk
space for the staged app and a full non-app prefix snapshot. Repeated updates can
accumulate large backups; no automatic backup-pruning policy is enabled yet.

## Interrupted updates and rollback

With Spark stopped:

```bash
spark-omarchy update --recover
```

Recovery restores the previously active application/state and does not launch
Spark. Never launch the executable directly with Wine while a journal exists;
that bypasses the managed lifecycle guarantees. Do not delete the journal or
state record just to suppress the guard.

Before the updated app has **ever been launched**:

```bash
spark-omarchy rollback --yes
```

That rolls back application files safely because no new app has had a chance to
migrate its data. The service's pre-start guard also records direct systemd starts,
not just CLI starts. A failed attempted start is conservatively treated as a
possible migration.

**After launch, automatic rollback is deliberately refused.** An old executable
may not understand a migrated mail database. Keep the current data and offline
snapshot; a recovery then needs a deliberate offline data-restore plan that
preserves any mail/drafts created after the update. This first phase does not
provide a one-command destructive data restore. Application rollback alone is
not a promise of schema compatibility.

## Spark's own updater

For the reviewed build, the service and callback processes set:

```text
NODE_CONFIG={"features":{"autoUpdaterDisabled":true}}
```

The bundled configuration loader accepts this override. A clean-prefix runtime
test confirmed the main process saw `autoUpdaterDisabled: true` for
`3.32.4.141552`; the temporary loopback inspector was stopped and removed afterward.
No inspector/debug port is part of an installed unit.

This disables the normal **background** self-update path. Do not invoke Spark's
manual update/restart menu or re-enable its automatic updater in the app. Those
are not rerouted through our approval mechanism. Startup validates the reviewed
executable/archive/Foundation hashes and refuses changed managed files. Every
new approved build must independently qualify its updater-control behavior.

## Maintainer approval/signing

No vendor version is automatically promoted. For each candidate:

1. Download directly from Spark, inspect the imports/bug and verify all artifact
   hashes. Qualify the native-updater flag and required client/shim ABI.
2. Run synthetic/native tests and clean-prefix startup tests. Obtain authorization
   for provider/mail tests; CI does not log in or download mail. Test a real upgrade
   separately before claiming that data migrations work.
3. Add the reviewed release to `updates/catalog.json`, select `recommended`, and
   set an accurate `minimum_client`. Unknown bundle/API behavior needs a client
   change, not a skipped check.
4. Sign locally using the **private key outside the checkout**, increasing the
   sequence beyond the currently published envelope:

```bash
./bin/sign-catalog --key /private/offline/location/update-signing.key --sequence 2
```

The tool requires owner-only key permissions, refuses keys inside the checkout,
checks that the signature matches the bundled public key, and defaults to 90 days.
Back up the private key securely outside the repo and vault. Prefer encrypted
or offline release-key storage: mode 0600 does **not** protect an unencrypted key
from other processes running as the same user, including Wine applications.
The signing tool can let OpenSSL prompt for an encrypted key's passphrase in an
interactive terminal; never paste that passphrase into chat or CI logs. This
project does not copy the key into CI secrets automatically. Renew an expiring catalog with a new
sequence even if the approved application list has not changed.

5. Review the catalog, signed envelope and documentation, run tests, then publish
   them together in one commit. **Never commit the signing key.** The signature
   protects clients from unapproved metadata changes; reviewers must still check
   that the approved app and compatibility claims are sound.

Automatic upstream-version discovery/draft PRs, unattended application, automatic
post-launch database rollback and automatic integration-code upgrades are not
part of this first phase.
