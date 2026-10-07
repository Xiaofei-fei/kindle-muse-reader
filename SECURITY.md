# Security

This app is for a **trusted private LAN**, with a single household operator. It uses the Python standard-library HTTP server for old Kindle browser compatibility. It is not hardened for hostile multi-user hosting, and the eight-digit code does not encrypt HTTP traffic. Keep the default loopback binding until you deliberately configure a LAN IPv4 address. Do not forward the port or publish a news mirror.

- Runtime directories are private; access codes and databases are 0600. SDK credentials belong to the SDK service account, separate from reader callbacks.
- Session cookies are HttpOnly / SameSite=Strict. Prompt submission requires a signed single-use request ID; HTTP access logs intentionally omit URLs and prompts.
- Read-only connection health is public; reader history, summaries and messages require login.
- Muse registers only three Kindle-specific commands. Callbacks drop to the dedicated reader account, which must have no sudo access.
- The optional SDK uses upstream pairing and encrypted transport. Pair only on a trusted network; account access and cloud availability are subject to upstream terms.
- Publisher fetches use a fixed HTTPS allowlist. Date checks do not certify that every news claim is true. Links and source text are untrusted.

Do not commit `state/`, tokens, pairing files, cookies, databases, Kindle backups, books or screenshots with personal records. The repository scanner helps detect accidental inclusion; it is a heuristic, not a proof that every possible secret is absent.

For an ordinary bug, open an issue using a synthetic reproduction. For a vulnerability, use GitHub's private vulnerability reporting if enabled for this repository. If it is unavailable, open an issue asking for a private reporting channel without publishing exploit details, credentials or private reader data.

Only the current main branch is maintained. Security fixes should include a meaningful regression check and preserve existing data.
