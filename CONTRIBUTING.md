# Contributing

Thanks for helping make this experiment reproducible rather than merely making
it launch once. Read [development](docs/development.md) and the
[security model](SECURITY.md) first.

## Useful issue reports

Include:

- Omarchy/Arch and Wine versions; x86_64 hardware category if relevant.
- Project version and the reviewed Spark version.
- Which setup command/step failed, and the visible sanitized error.
- `spark-omarchy doctor --json` output after reviewing it for anything private.
- Whether this was a fresh prefix, whether login succeeded, and whether the issue
  occurs during initial sync or when apparently idle.
- For OAuth, the provider and **scheme name only**, never the callback URL.

Do not attach mail, account addresses, codes/state/tokens, cookies, a Wine prefix,
raw application logs, crash dumps or screenshots containing personal content.
Do not run support scripts that upload those files. Ask before escalating to
sensitive diagnostics.

## Pull requests

- Keep dependencies small and failures explicit.
- Add a regression test for behavior changes; run `./bin/test` and native API
  tests when changing the shim/build.
- Preserve the version/hash guard, exact argument forwarding, selective handler
  rollback and data-preserving uninstall.
- Do not add a hard CPU cap as a default; it made the UI crawl in testing.
- Do not add a remote-debugging endpoint, automatic root elevation or login
  autostart by default.
- Do not commit vendor binaries/icons, generated artifacts, private paths or
  personal test data. Use synthetic fixtures.
- Document what was actually tested and what was not; CI cannot prove real mail
  reliability. Provider-specific flows need their own qualification.

This project's source is MIT licensed. Contributions must be code you have the
right to submit; do not paste proprietary Spark implementation code or relicense
Wine code as ours. An upstream Wine fix should follow Wine's contribution and
licensing requirements separately.
