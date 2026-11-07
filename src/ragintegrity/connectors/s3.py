"""Read-only S3 source inventory.

Only ListObjectsV2 / HeadObject (and GetObject in ``compute`` mode) are used, so a read-only IAM
policy is enough. Object *contents* are streamed through a hash function and discarded.

Why not just use the ETag? For multipart uploads the ETag is not a content hash (it looks like
``<md5-of-md5s>-<parts>``) and changes if the same bytes are re-uploaded with a different part
size. Hash modes:

metadata  use the ``sha256`` user-metadata key or S3's additional SHA-256 checksum (needs one HEAD per object)
compute   stream the object and hash it ourselves (always right, costs egress/time)
etag      use the ETag; flagged ``hash_reliable=False`` when it is a multipart ETag
"""

from __future__ import annotations

import base64
import re
import time
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import timezone
from typing import Any

from ..config import Settings
from ..models import ConnectionStatus, Scope, SourceDoc
from .base import ConnectorError

DIRECT_HEAD_LIMIT = 500  # scoped runs for <= this many documents HEAD objects directly instead of listing


class S3Source:
    def __init__(self, settings: Settings, client: Any = None) -> None:
        if not settings.s3_bucket:
            raise ConnectorError("RAGI_S3_BUCKET is not set")
        self.s = settings
        self.bucket = settings.s3_bucket
        self.prefix = settings.s3_prefix
        self.pattern = re.compile(settings.s3_key_pattern)
        self.has_tenant_group = "tenant_id" in self.pattern.groupindex
        if "document_id" not in self.pattern.groupindex:
            raise ConnectorError("RAGI_S3_KEY_PATTERN must contain a (?P<document_id>...) group")
        if client is None:
            import boto3

            client = boto3.client("s3", region_name=settings.s3_region, endpoint_url=settings.s3_endpoint_url)
        self.client = client

    # --------------------------------------------------------------------------------- keys
    def parse_key(self, key: str) -> tuple[str, str] | None:
        rel = key[len(self.prefix):] if key.startswith(self.prefix) else key
        if not rel or rel.endswith("/"):
            return None
        m = self.pattern.match(rel)
        if not m:
            return None
        g = m.groupdict()
        return (g.get("tenant_id") or self.s.s3_default_tenant, g["document_id"])

    def to_key(self, tenant: str, doc: str) -> str:
        return f"{self.prefix}{tenant}/{doc}" if self.has_tenant_group else f"{self.prefix}{doc}"

    # --------------------------------------------------------------------------------- inventory
    def inventory(self, scope: Scope | None = None) -> Iterator[SourceDoc]:
        if scope is not None and scope.keys is not None and len(scope.keys) <= DIRECT_HEAD_LIMIT:
            yield from self._direct(scope)
            return
        prefix = self.prefix
        if scope is not None and scope.tenant and self.has_tenant_group:
            prefix = f"{self.prefix}{scope.tenant}/"
        listed: list[tuple[str, dict[str, Any]]] = []
        paginator = self.client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
            for obj in page.get("Contents", []):
                parsed = self.parse_key(obj["Key"])
                if parsed is None or (scope is not None and not scope.matches(parsed)):
                    continue
                listed.append((obj["Key"], obj))
        if self.s.s3_hash_mode == "etag":
            for key, obj in listed:
                yield self._doc(key, obj, None)
            return
        with ThreadPoolExecutor(max_workers=max(1, self.s.s3_workers)) as pool:
            yield from pool.map(lambda item: self._resolve(*item), listed)

    def _direct(self, scope: Scope) -> Iterator[SourceDoc]:
        assert scope.keys is not None
        def one(k: tuple[str, str]) -> SourceDoc | None:
            key = self.to_key(*k)
            try:
                head = self.client.head_object(Bucket=self.bucket, Key=key, ChecksumMode="ENABLED")
            except Exception as exc:
                code = getattr(exc, "response", {}).get("Error", {}).get("Code")
                if code in ("404", "NoSuchKey", "NotFound"):
                    return None
                raise
            obj = {"Key": key, "Size": head.get("ContentLength", 0), "ETag": head.get("ETag", ""),
                   "LastModified": head.get("LastModified")}
            return self._doc(key, obj, head)
        with ThreadPoolExecutor(max_workers=max(1, self.s.s3_workers)) as pool:
            for doc in pool.map(one, sorted(scope.keys)):
                if doc is not None:
                    yield doc

    def _resolve(self, key: str, obj: dict[str, Any]) -> SourceDoc:
        head = self.client.head_object(Bucket=self.bucket, Key=key, ChecksumMode="ENABLED")
        return self._doc(key, obj, head)

    def _doc(self, key: str, obj: dict[str, Any], head: dict[str, Any] | None) -> SourceDoc:
        tenant, doc_id = self.parse_key(key)  # type: ignore[misc]
        etag = (obj.get("ETag") or "").strip('"')
        sha: str | None = None
        reliable = True
        version = (head or {}).get("VersionId")
        mode = self.s.s3_hash_mode
        if mode == "etag" or head is None:
            sha, reliable = etag or None, "-" not in etag
        else:
            meta = {k.lower(): v for k, v in (head.get("Metadata") or {}).items()}
            sha = meta.get(self.s.s3_sha256_metadata_key.lower())
            if sha is None and head.get("ChecksumSHA256"):
                sha = base64.b64decode(head["ChecksumSHA256"]).hex()
            if sha is None and mode == "compute":
                sha = self._compute_sha256(key)
            if sha is None:  # nothing better available: degrade to the ETag and say so
                sha, reliable = etag or None, "-" not in etag
        lm = obj.get("LastModified")
        return SourceDoc(
            tenant_id=tenant, document_id=doc_id, source_uri=f"s3://{self.bucket}/{key}",
            source_version=version or etag or None, source_hash=sha, hash_reliable=reliable,
            size_bytes=int(obj.get("Size") or 0),
            last_modified=lm.astimezone(timezone.utc).isoformat().replace("+00:00", "Z") if lm else None,
        )

    def _compute_sha256(self, key: str) -> str:
        import hashlib

        h = hashlib.sha256()
        body = self.client.get_object(Bucket=self.bucket, Key=key)["Body"]
        for chunk in iter(lambda: body.read(1024 * 1024), b""):
            h.update(chunk)
        return h.hexdigest()

    def health(self) -> ConnectionStatus:
        t0 = time.perf_counter()
        try:
            resp = self.client.list_objects_v2(Bucket=self.bucket, Prefix=self.prefix, MaxKeys=5)
            ms = (time.perf_counter() - t0) * 1000
            sample = [o["Key"] for o in resp.get("Contents", [])]
            unparsed = [k for k in sample if self.parse_key(k) is None]
            detail = f"bucket '{self.bucket}' reachable, hash mode '{self.s.s3_hash_mode}'"
            if unparsed:
                detail += f"; {len(unparsed)} sample key(s) don't match RAGI_S3_KEY_PATTERN"
            return ConnectionStatus("S3 source", "s3", True, detail, ms, {"sample_keys": sample})
        except Exception as exc:
            return ConnectionStatus("S3 source", "s3", False, _short(exc))


def _short(exc: Exception) -> str:
    return f"{type(exc).__name__}: {str(exc)[:200]}"
