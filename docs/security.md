# Security model (multi-user app mode)

`RAGI_MODE=app` turns RAG Integrity into a multi-user service: anyone can register (unless you close sign-up), and each
user connects *their own* S3, manifest database and Qdrant. That means the server holds other people's credentials and makes
network connections to hosts they type in, so these are the controls, what they cover, and what they do not.

## Accounts and sessions

| Control | How it works |
|---|---|
| Passwords | scrypt (N=2^14, r=8, p=1) with a per-user salt, constant-time compare. 10-128 characters; common passwords, repeated-character passwords and passwords containing the email name are refused. |
| No user enumeration | Login errors are identical for "wrong password" and "no such account", and an unknown email still spends the same CPU time as a real check. (Registration does say an email is taken: it has to.) |
| Sessions | A random 256-bit token in an `HttpOnly`, `SameSite=Lax`, `Secure` (over HTTPS) cookie. Only the SHA-256 of the token is stored, so a database leak does not leak live sessions. 7-day sliding expiry; logout and password change revoke server-side. |
| CSRF | `SameSite=Lax` plus an `Origin`/`Referer` check on every cookie-authenticated write. |
| Brute force | Database-backed counters (they hold across serverless instances): 8 attempts per account and 30 per network per 15 minutes, 5 sign-ups per network per hour, 30 connection tests per workspace per 10 minutes. |
| Closing sign-up | `RAGI_ALLOW_REGISTRATION=false` (existing users can still sign in). |

## Tenant isolation

Every ledger table carries a `workspace_id`, and a `Ledger` object is bound to exactly one workspace: every statement it builds
carries that condition, so there is no code path that reads or writes across workspaces. `tests/test_accounts.py` attacks this
directly (reading, modifying, ignoring, resolving, resetting and hijacking a plan by id across workspaces) and
`tests/test_postgres_integration.py` repeats the core cases on a real Postgres. The one deliberate cross-workspace lookup is
`workspace_of_plan`, used to route a *signed* worker callback.

## Customer credentials

* The admin dashboard (`/admin`, `/api/admin/*`) is open only to a signed-in session whose email is in `RAGI_ADMIN_EMAILS`;
  API keys never open it and everyone else gets a 404. It is read-only and returns no secrets, settings values, IP addresses or
  browser strings. A listed email cannot be registered through the sign-up form, because sign-up does not verify addresses.
* S3 keys, database URLs, Qdrant keys, the alert webhook URL, the repair signing secret and the SMTP password are encrypted with Fernet (AES-128-CBC + HMAC-SHA256) under
  `RAGI_SECRET_KEY` before they reach the database. The key exists only in the server environment. Rotate by setting
  `RAGI_SECRET_KEY="<new>,<old>"`: the first encrypts, all decrypt.
* Secrets are write-only through the API and UI: a saved secret is shown as "saved", never returned.
* Error messages and ledger rows are scrubbed of `scheme://user:password@host` credentials. A failed alert or repair delivery
  never records the webhook address (a secret: a Slack URL's path is the credential), not even as a redirect target or a host
  named in a TLS error; run rows stored before that was fixed have web addresses removed when they are read.
* Everything is read-only by design: S3 `list`/`head` (and `get` only in `compute` hash mode); every manifest query runs in a
  `READ ONLY` transaction with a statement timeout; Qdrant `scroll`/`retrieve`/`query`. The connection test warns if the
  database role could write.

## Outbound connections (SSRF)

Users give the server hostnames to connect to, which is a classic SSRF risk. Every target (S3 endpoint, Qdrant URL, manifest
database, repair and alert webhooks) is validated when saved **and again right before each connection**:

* the host must be public: loopback, RFC 1918, link-local (including the cloud metadata address `169.254.169.254`), CGNAT,
  IPv4-mapped IPv6, multicast and reserved ranges are refused, and a hostname is resolved and *every* address must be public
  (DNS-rebinding style answers with one private record are refused);
* no credentials inside URLs, only `http(s)`, only `postgresql://` for databases, no unix sockets, and a connection-string option
  allow-list (`sslmode`, `connect_timeout`, `application_name`) so `hostaddr=` or `options=` cannot smuggle a target;
* `RAGI_ALLOW_PRIVATE_HOSTS=true` lifts the restriction for self-hosting next to your own services.

Residual risk: validation resolves the name, and the client resolves it again when connecting, so a DNS answer that changes in
between is a narrow race. If you run this for untrusted users, also restrict egress at the network layer.

## API keys

For CI, cron and retrieval-log ingestion. A key (`ragi_...`, shown once, stored hashed) acts only inside its workspace and can run
audits and read results, but it cannot read settings, create keys or change passwords. Revocation is immediate.

## Web hardening

Strict `Content-Security-Policy` (`script-src 'self'`), `X-Frame-Options: DENY`, `nosniff`, no referrer, `no-store` on API
responses. The web interface renders every value as text (document ids come from S3 keys, so they are attacker-influenced).

## Not covered (be aware)

* **No email verification and no self-service password reset** (the optional platform mail account only sends audit alerts and
  test emails). The operator resets a forgotten password with `ragi users set-password EMAIL`: same rules as sign-up, every session
  of that user is signed out, and the sign-in lockout for that email is cleared. Treat sign-up as open to anyone who can reach the
  URL; close it with `RAGI_ALLOW_REGISTRATION=false` once your team has accounts.
* **No two-factor authentication, no teams/roles**: one user owns one workspace.
* The vault protects secrets at rest against database exposure, not against someone who can read the server environment.
* Audits on serverless are limited by the function's time limit (a clear message tells you to scope them or run `ragi audit`).
