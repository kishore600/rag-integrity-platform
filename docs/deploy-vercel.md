# Deploying to Vercel

The dashboard and API run as a single FastAPI serverless function. Live demo: https://rag-integrity-platform.vercel.app

## How it is wired

| File | Purpose |
|---|---|
| `api/index.py` | entrypoint: adds `src/` to the path, defaults to `RAGI_MODE=demo` and an ephemeral SQLite ledger in `/tmp`, exposes `app` |
| `requirements.txt` | the *only* install source on Vercel (`.vercelignore` hides `pyproject.toml`): FastAPI, SQLAlchemy, psycopg, httpx. `boto3` and `qdrant-client` are deliberately left out (live mode only) |
| `vercel.json` | `maxDuration: 60`, bundles `src/**`. **No rewrites**, see below |

```bash
npx vercel login                       # once
npx vercel link --project rag-integrity-platform
npx vercel deploy                      # preview
npx vercel curl /healthz --deployment <url>        # test it even behind Deployment Protection
npx vercel promote <url>               # promote the build you just tested to production
```

`vercel link` also connects the GitHub repository, so every push to `main` deploys to production automatically.

## Serverless behaviour you should know about

* **No rewrite rule.** Vercel recognises FastAPI and routes every path to the app. A catch-all rewrite to `/api/index`
  makes the app see `/api/index` as the path, so *every* route returns 404. `tests/test_serverless.py` guards this.
* **Audits run inside the request** (implied by the `VERCEL` environment variable, or `RAGI_SYNC_AUDITS=true`). A background
  thread is frozen once the response is sent. The dashboard handles both modes.
* **Start-up is lazy.** The first `/api/*` request seeds the demo (`ensure_ready`) instead of relying on ASGI lifespan hooks.
  `/healthz` stays cheap and never triggers it. A failed bootstrap returns a 503 *without* leaking the connection string, and retries.
* **The demo's state is per instance.** The default ledger is SQLite in `/tmp` and the synthetic world lives in memory, so both
  reset together on a cold start and a second concurrent instance has its own copy. For a single viewer that is invisible; it
  is not a database.
* **The scheduler (`RAGI_AUDIT_INTERVAL_MINUTES`) does nothing on Vercel**, because there is no long-lived process. Schedule
  audits from outside: `ragi audit --fail-on high` in cron/CI, or a scheduled workflow that calls `POST /api/audits`.

## Making it persistent (live mode)

A Postgres/Supabase ledger on Vercel only makes sense together with **live mode**, where S3, the manifest and Qdrant are the
persistent source of truth. (With the synthetic demo world, a persistent ledger would disagree with a world that resets on every
cold start.) Set these in *Project Settings -> Environment Variables*, never in the repo:

```
RAGI_MODE=live
RAGI_DATABASE_URL=postgresql://postgres.<ref>:<password>@aws-0-<region>.pooler.supabase.com:5432/postgres?sslmode=require
RAGI_S3_BUCKET=...   RAGI_MANIFEST_DATABASE_URL=...   RAGI_QDRANT_URL=...   (see configuration.md)
RAGI_API_KEY=<long random string>
```

then add `boto3` and `qdrant-client` to `requirements.txt`, and put the function next to the database to keep latency low
(e.g. `"regions": ["icn1"]` in `vercel.json` for a Seoul Supabase project; Hobby allows one region). Large corpora will not
finish an audit inside the 60 s function limit: run those audits from cron/CI and use Vercel for the dashboard.

## Access control

* Vercel's default *Standard Protection* leaves the production domain public but puts a Vercel login in front of the unique
  per-deployment URLs.
* The demo ships **without an API key**, so anyone with the production URL can click through it. That is fine for synthetic,
  ephemeral data. For anything real, set `RAGI_API_KEY` (the dashboard then asks for it) and/or enable *Vercel Authentication*
  for production in the project settings.
