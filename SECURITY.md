# Security and trust boundaries

This is an unofficial compatibility experiment handling an authenticated mail
application. It is not a security-hardening project or a sandbox.

## What to trust

You must trust this source/build, Wine, your desktop account and Spark's vendor
software/services. The installer downloads the pinned app directly from its
vendor over HTTPS and verifies whole-file SHA-256 pins before extracting it.
Hashes establish reviewed identity, not an independently verified vendor
signature. We modify a local Foundation DLL, invalidating its signature.

Spark keeps its own licensing, privacy policy and network/account behavior. We do
not proxy its mail traffic, disable TLS checks, bypass OAuth state validation,
bypass subscriptions, or implement account authentication ourselves. A Wine
prefix can access your ordinary user files; separate configuration does not
protect them from the app.

## Callback handling

Callbacks can contain single-use authorization codes and state. The bridge:

- accepts only the reviewed Spark OAuth schemes;
- rejects control characters and oversized inputs;
- passes the exact URL as one argv element without a shell;
- does not print URL contents, put them in a unit description/file, or capture
  child stdout/stderr;
- does not read cookies, codes, tokens or credentials.

Delivering a callback necessarily exposes it to the receiving app's process
arguments and transient systemd metadata while active. Same-user processes and
privileged users are inside that trust boundary. App-generated internal logs
may also contain sensitive data; this tool does not sanitize Spark's own logs.
Never post a callback URL, a prefix, unreviewed logs, crash dumps or authenticated
screenshots publicly. `doctor` intentionally collects metadata only.

## Ownership and deletion

Installation is per-user and rejects root execution, unrelated existing files,
unknown prefixes, unsupported hashes/imports and symlinked managed state. An
ownership record is saved before integration changes. Uninstall preserves data
unless both `--yes` and `--purge-data` are requested. Existing browser/mailto
defaults are not replaced. Handler restoration is selective, not a rollback of
your entire MIME configuration.

This does not defend against a malicious process running as the same user
modifying state/files concurrently. Do not run setup in an untrusted shared HOME
or XDG directory. The systemd user manager and graphical session must belong to
the same intended user.

## Approved update channel

Automatic updates stop at authenticated metadata checks and verified downloads.
The daily timer cannot apply an update or force-close Spark. Ed25519 approval
signatures use a public key bundled with the client, a bounded/expiring catalog,
and locally monotonic sequences. Only canonical vendor URLs and reviewed hashes,
layouts and shim ABIs are accepted. A new integration client is required when
approval metadata declares a newer minimum version. This is not a self-updating
code execution pipeline or a complete TUF implementation.

Explicit application while fully stopped makes a private offline prefix snapshot
and a journaled application switch. Snapshots can contain credentials/mail and
are not encrypted by this project, uploaded, or automatically pruned. They require
at least the same protection as the live prefix. Starts are blocked by unfinished
journals. Automatic rollback is refused after launch because data may have been
migrated; restoring only an executable is not safe schema recovery.

The maintainer's private signing key is never shipped to clients or CI. Owner-only
permissions do not protect a plaintext key from same-user processes, including
Wine apps: use encrypted/offline key storage and keep it out of the repo/KB.
See [update trust, recovery and signing](docs/updates.md) for the precise limits.

## Reporting a vulnerability

If GitHub's private vulnerability reporting is available for this repository,
use it. Otherwise open a minimal issue asking for a private reporting channel,
without sensitive data or exploit payloads that expose another user's account.
Never include real OAuth secrets, passwords or mail as a reproduction.

No supported-production security guarantee is made. Pinned old vendor builds
need ongoing review; if a security update requires a new app version, do not
keep using an unsafe old build merely to retain compatibility.
