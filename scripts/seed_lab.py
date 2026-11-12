"""Write the practice lab (30 documents with every fault planted, plus the mini bills lab) into LOCAL S3 / PostgreSQL / Qdrant.

    docker compose -f docker-compose.lab.yml up --build      # runs this for you

It never reads `.env` or the app's RAGI_* settings, so it cannot be pointed at your real systems by accident, and it refuses
any host that is not this computer or one of the lab's containers. Safe to re-run: it recreates the lab's tables and collections.

Variables (all optional; the defaults match docker-compose.lab.yml run from your computer):
    LAB_S3_ENDPOINT   http://127.0.0.1:9000        LAB_S3_BUCKET  docs   AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY  minioadmin
    LAB_PG_URL        postgresql://postgres:postgres@127.0.0.1:55432/postgres
    LAB_QDRANT_URL    http://127.0.0.1:6333        LAB_QDRANT_API_KEY (none)
"""

from __future__ import annotations

import os
import sys
import time
from urllib.parse import urlparse

import boto3
from qdrant_client import QdrantClient
from sqlalchemy import create_engine

from ragintegrity.config import normalize_db_url
from ragintegrity.demo.lab import BILLS_BUCKET, assert_local, seed_everything


def wait_for(label: str, fn, tries: int = 60) -> None:
    for i in range(tries):
        try:
            fn()
            return
        except Exception as exc:
            if i == tries - 1:
                raise SystemExit(f"{label} did not come up: {type(exc).__name__}: {str(exc)[:160]}") from exc
            print(f"waiting for {label} ...", flush=True)
            time.sleep(2)


def main() -> int:
    s3_url = os.environ.get("LAB_S3_ENDPOINT", "http://127.0.0.1:9000")
    pg_url = os.environ.get("LAB_PG_URL", "postgresql://postgres:postgres@127.0.0.1:55432/postgres")
    qd_url = os.environ.get("LAB_QDRANT_URL", "http://127.0.0.1:6333")
    bucket = os.environ.get("LAB_S3_BUCKET", "docs")
    for label, url in (("S3", s3_url), ("PostgreSQL", pg_url), ("Qdrant", qd_url)):
        assert_local(label, urlparse(url).hostname)

    s3 = boto3.client("s3", region_name="us-east-1", endpoint_url=s3_url,
                      aws_access_key_id=os.environ.get("AWS_ACCESS_KEY_ID", "minioadmin"),
                      aws_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY", "minioadmin"))
    wait_for("S3", lambda: s3.list_buckets())
    engine = create_engine(normalize_db_url(pg_url), connect_args={"prepare_threshold": None})
    wait_for("PostgreSQL", lambda: engine.connect().close())
    qdrant = QdrantClient(url=qd_url, api_key=os.environ.get("LAB_QDRANT_API_KEY") or None, check_compatibility=False)
    wait_for("Qdrant", lambda: qdrant.get_collections())

    world = seed_everything(s3, bucket, engine, qdrant, bills_bucket=os.environ.get("LAB_BILLS_BUCKET", BILLS_BUCKET))
    print(f"\nDone. Lab A planted {len(world.faults)} faulty documents (see lab/WORKBOOK.md). Open the apps and run an audit:\n"
          "  Lab A  http://localhost:8000     Lab B (mini bills)  http://localhost:8001")
    return 0


if __name__ == "__main__":
    sys.exit(main())
