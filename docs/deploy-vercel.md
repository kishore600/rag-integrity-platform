# Deploying to Vercel (multi-user app)

The web interface and API run as one FastAPI serverless function. Users sign up, then connect **their own** S3, processing manifest
(Postgres) and Qdrant in *Settings*. There is no sample data: a new workspace is empty until it is connected.

## What you need

| | |
|---|---|
| A Postgres database | Supabase is the intended home: accounts, sessions, encrypted connection secrets and the ledger live there. Apply `supabase/migrations/` (`supabase db push`). |
| `RAGI_DATABASE_URL` | its connection string. On serverless use Supabase's **transaction pooler** (port 6543, `postgres.<ref>` user). |
| `RAGI_SECRET_KEY` | 32+ random characters. Encrypts the secrets users store. Keep a copy: without it, stored secrets cannot be decrypted. |

Until both variables are set the app shows a **Setup required** screen that says exactly what is missing. It never falls back to a
temporary database: serverless storage is ephemeral, so accounts created there would silently disappear.

## One-time setup

```bash
npx vercel login
npx vercel link --project rag-integrity-platform
supabase link --project-ref <ref> && supabase db push        # creates the 13 tables (row level security on, anon locked out)
```

Then put your connection string in `.env` as `RAGI_DATABASE_URL=...` (git-ignored) and run **yourself**:

```bash
powershell -ExecutionPolicy Bypass -File scripts\vercel-env.ps1
```

It reads `RAGI_DATABASE_URL` from `.env`, generates `RAGI_SECRET_KEY` if you have none (and saves it to `.env`), and sets both
on the Vercel project as *sensitive* (write-only) variables without ever printing them. `-DryRun` shows what it would do.
Then deploy: `npx vercel deploy --prod` (or push to `main`: the GitHub repo is connected, so every push deploys).

## Other environment variables

| Variable | Default | |
|---|---|---|
| `RAGI_ALLOW_REGISTRATION` | `true` | set `false` to close sign-up once your team has accounts (there is no email verification) |
| `RAGI_ALLOW_PRIVATE_HOSTS` | `false` | leave off on a public deployment: it is the SSRF guard |
| `RAGI_SESSION_DAYS` | `7` | |
| `RAGI_MAX_AUDIT_SECONDS` | 50 on Vercel | an audit that runs longer stops with a clear message |

## Serverless behaviour you should know about

* **No rewrite rule in `vercel.json`.** Vercel recognises FastAPI and routes every path to the app. A catch-all rewrite to
  `/api/index` makes the app see `/api/index` as the path, so every route 404s. `tests/test_serverless.py` guards this.
* **Audits run inside the request.** A background thread is frozen once the response is sent, so audits finish (or stop with a
  time-budget message) within the function's limit (`maxDuration` 60 s). Thousands of documents are fine; for very large corpora
  audit one tenant at a time (`POST /api/audits {"tenant": "..."}`) or run `ragi audit` elsewhere.
* **Only one audit per workspace at a time**, enforced by a database index, so it holds across concurrent function instances.
* **Scheduled audits**: there is no long-lived process, so schedule from outside. Create an API key in Settings, then call
  `POST /api/audits` from GitHub Actions, cron or any scheduler (the Settings page shows the exact `curl`).
* **Cold start** imports the app only; `boto3`, `qdrant-client` and the database driver are loaded when first needed.
* The Linux bundle is ~160 MB of the 250 MB function limit; keep `requirements.txt` lean.

## Pointing it at your infrastructure

In *Settings* each connection has a **Save & test** button that runs the real connector and reports what it found: the bucket and how
many sampled keys match your key pattern, how many objects carry a SHA-256, whether the manifest table and columns are mapped and the
database role is read-only, which Qdrant collections exist and whether their payloads carry `document_id` and `source_hash`.

* **Supabase Storage as the source:** endpoint `https://<ref>.supabase.co/storage/v1/s3`, region of the project, access keys from
  *Project Settings -> Storage -> S3 Connection*.
* **Supabase / Postgres manifest:** use a role that can only `SELECT` (template in `supabase/examples/manifest_example.sql`).
* Targets must be reachable from the internet: private and loopback addresses are refused (see [security.md](security.md)).

## Operating it

```bash
ragi users list                       # who has signed up (needs RAGI_DATABASE_URL and RAGI_SECRET_KEY locally)
ragi users delete someone@example.com --yes   # removes the user and everything in their workspace
```

Roll back a bad deploy with `npx vercel promote <previous-deployment-url>`.
