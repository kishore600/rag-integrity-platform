"""Vercel entrypoint: exposes the FastAPI app as a serverless function.

This is the multi-user product (RAGI_MODE=app): sign-up / login, and each workspace connects its own S3, processing
manifest and Qdrant. It needs two environment variables in the Vercel project (see docs/deploy-vercel.md):

  RAGI_DATABASE_URL   a Postgres / Supabase connection string (accounts, sessions, encrypted connection secrets, ledger)
  RAGI_SECRET_KEY     >= 32 random characters; encrypts stored connection secrets

Until both are set the app starts in a "setup required" state that says exactly what is missing. It deliberately never
falls back to a temporary database: serverless storage is ephemeral, so accounts created there would silently vanish.
Audits run inside the request (RAGI_SYNC_AUDITS is implied on Vercel); background threads are frozen after the response.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

os.environ.setdefault("RAGI_MODE", "app")

from ragintegrity.api.app import create_app  # noqa: E402

app = create_app()
