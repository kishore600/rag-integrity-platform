"""Vercel entrypoint: exposes the FastAPI app as a serverless function (see vercel.json for the rewrite).

Serverless notes
* The filesystem is read-only except /tmp, so the default ledger is an ephemeral SQLite file there. For anything you want
  to keep, set RAGI_DATABASE_URL to a Postgres / Supabase connection string in the Vercel project settings.
* Demo mode needs no external infrastructure. For live mode add boto3 and qdrant-client to requirements.txt and set the
  RAGI_S3_* / RAGI_MANIFEST_* / RAGI_QDRANT_* variables.
* Audits run inside the request (RAGI_SYNC_AUDITS is implied on Vercel); background threads are frozen after the response.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

os.environ.setdefault("RAGI_MODE", "demo")
os.environ.setdefault("RAGI_DATABASE_URL", "sqlite:////tmp/ragi.db")

from ragintegrity.api.app import create_app  # noqa: E402

app = create_app()
