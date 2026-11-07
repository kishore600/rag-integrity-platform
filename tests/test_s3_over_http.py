"""The S3 connector against an S3 API served over REAL HTTP with a custom endpoint and path-style addressing.

This is how users of Supabase Storage, MinIO or R2 connect, and it exercises what the in-process mock cannot: request
signing, the endpoint URL and the wire format. Skipped unless RAGI_TEST_S3_ENDPOINT is set, e.g. with
    moto_server -p 5556     (or a MinIO / Supabase Storage endpoint plus RAGI_TEST_S3_KEY / RAGI_TEST_S3_SECRET)
"""

from __future__ import annotations

import hashlib
import os

import boto3
import pytest
from botocore.config import Config

from ragintegrity.config import Settings
from ragintegrity.connectors.s3 import S3Source
from ragintegrity.models import Scope

ENDPOINT = os.environ.get("RAGI_TEST_S3_ENDPOINT")
ACCESS = os.environ.get("RAGI_TEST_S3_KEY", "test-access-key")
SECRET = os.environ.get("RAGI_TEST_S3_SECRET", "test-secret-key")
pytestmark = pytest.mark.skipif(not ENDPOINT, reason="RAGI_TEST_S3_ENDPOINT not set")
BUCKET = "ragi-wire-test"


def settings(**kw) -> Settings:
    return Settings(_env_file=None, s3_bucket=BUCKET, s3_region="us-east-1", s3_endpoint_url=ENDPOINT, s3_access_key_id=ACCESS,
                    s3_secret_access_key=SECRET, **kw)


@pytest.fixture(scope="module")
def seeded():
    s3 = boto3.client("s3", region_name="us-east-1", endpoint_url=ENDPOINT, aws_access_key_id=ACCESS, aws_secret_access_key=SECRET,
                      config=Config(s3={"addressing_style": "path"}))
    try:
        s3.create_bucket(Bucket=BUCKET)
    except Exception:
        pass
    docs = {"acme/policies/leave.md": b"leave policy", "acme/runbooks/db.md": b"runbook", "globex/readme.md": b"hello"}
    for key, body in docs.items():
        s3.put_object(Bucket=BUCKET, Key=key, Body=body, Metadata={"sha256": hashlib.sha256(body).hexdigest()})
    s3.put_object(Bucket=BUCKET, Key="acme/no-hash.md", Body=b"no metadata hash")
    s3.put_object(Bucket=BUCKET, Key="acme/folder/", Body=b"")
    return docs


def test_inventory_over_http_with_custom_endpoint_and_path_style(seeded):
    got = {d.key: d for d in S3Source(settings()).inventory()}
    assert set(got) == {("acme", "policies/leave.md"), ("acme", "runbooks/db.md"), ("globex", "readme.md"), ("acme", "no-hash.md")}
    leave = got[("acme", "policies/leave.md")]
    assert leave.source_hash == hashlib.sha256(seeded["acme/policies/leave.md"]).hexdigest() and leave.hash_reliable
    assert leave.source_uri == f"s3://{BUCKET}/acme/policies/leave.md" and leave.size_bytes == len(b"leave policy")
    fallback = got[("acme", "no-hash.md")]  # no sha256 stored: falls back to the ETag, which is a plain md5 here
    assert fallback.source_hash == hashlib.md5(b"no metadata hash").hexdigest() and fallback.hash_reliable


def test_compute_mode_streams_and_hashes_over_http(seeded):
    got = {d.key: d for d in S3Source(settings(s3_hash_mode="compute")).inventory()}
    assert got[("acme", "no-hash.md")].source_hash == hashlib.sha256(b"no metadata hash").hexdigest()


def test_scoped_inventory_over_http(seeded):
    src = S3Source(settings())
    assert {d.key for d in src.inventory(Scope(tenant="globex"))} == {("globex", "readme.md")}
    one = list(src.inventory(Scope(keys=frozenset({("acme", "runbooks/db.md"), ("acme", "gone.md")}))))
    assert [d.key for d in one] == [("acme", "runbooks/db.md")]


def test_diagnostics_over_http(seeded):
    checks = {c["name"]: c for c in S3Source(settings(), fast=True).diagnose()}
    assert checks["Bucket reachable"]["status"] == "ok" and checks["Key pattern"]["status"] in ("ok", "warn")
    assert checks["Content hashes"]["status"] in ("ok", "warn")


def test_missing_bucket_and_dead_endpoint_are_explained(seeded):
    miss = S3Source(Settings(_env_file=None, s3_bucket="no-such-bucket-xyz", s3_region="us-east-1", s3_endpoint_url=ENDPOINT,
                             s3_access_key_id=ACCESS, s3_secret_access_key=SECRET), fast=True).diagnose()
    assert miss[0]["status"] == "fail" and "bucket does not exist" in miss[0]["detail"]
    dead = S3Source(Settings(_env_file=None, s3_bucket=BUCKET, s3_region="us-east-1", s3_endpoint_url="http://127.0.0.1:1",
                             s3_access_key_id=ACCESS, s3_secret_access_key=SECRET), fast=True).diagnose()
    assert dead[0]["status"] == "fail" and "Could not connect" in dead[0]["detail"]
