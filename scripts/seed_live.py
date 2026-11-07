"""Seed demo infrastructure (S3 / Postgres manifest / Qdrant) with the synthetic corpus and its injected faults.

Reads the same RAGI_* variables as the app, plus the standard AWS_* ones. Safe to re-run: it recreates the demo
manifest tables and Qdrant collection and overwrites the demo objects. NEVER point this at real data.
"""

from __future__ import annotations

import os
import sys
import time

import boto3
from qdrant_client import QdrantClient
from sqlalchemy import create_engine

from ragintegrity.config import get_settings, normalize_db_url
from ragintegrity.demo.seed import seed_manifest, seed_qdrant, seed_s3
from ragintegrity.demo.world import DemoWorld


def wait_for(label: str, fn, tries: int = 40) -> None:
    for i in range(tries):
        try:
            fn()
            return
        except Exception as exc:
            if i == tries - 1:
                raise
            print(f"waiting for {label}: {type(exc).__name__}", flush=True)
            time.sleep(2)


def main() -> int:
    s = get_settings()
    if not (s.s3_bucket and s.manifest_database_url and s.qdrant_url):
        print("Set RAGI_S3_BUCKET, RAGI_MANIFEST_DATABASE_URL and RAGI_QDRANT_URL first.", file=sys.stderr)
        return 2
    if "supabase.co" in s.manifest_database_url or "supabase.com" in s.manifest_database_url:
        print("Refusing to seed a Supabase database: this script drops and recreates the manifest tables.", file=sys.stderr)
        return 2
    world = DemoWorld(seed=int(os.environ.get("RAGI_DEMO_SEED", "7")))

    s3 = boto3.client("s3", region_name=s.s3_region, endpoint_url=s.s3_endpoint_url)
    wait_for("S3", lambda: s3.list_buckets())
    print(f"S3: {seed_s3(s3, s.s3_bucket, world, s.s3_prefix)} objects")

    engine = create_engine(normalize_db_url(s.manifest_database_url), connect_args={"prepare_threshold": None})
    wait_for("Postgres", lambda: engine.connect().close())
    print(f"Manifest: {seed_manifest(engine, world, schema=s.manifest_schema)} rows")

    qdrant = QdrantClient(url=s.qdrant_url, api_key=s.qdrant_api_key)
    wait_for("Qdrant", lambda: qdrant.get_collections())
    print(f"Qdrant: {seed_qdrant(qdrant, world, collection=(s.collections or ['kb_main'])[0])} points")
    print(f"Done. {len(world.faults)} documents carry an injected fault. Open the dashboard and run an audit.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
