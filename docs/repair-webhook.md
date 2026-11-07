# Repair webhook contract

RAG Integrity is read-only. To repair, it POSTs a signed JSON payload to **your** worker
(`RAGI_REPAIR_WEBHOOK_URL`); your worker does the writing. A runnable reference lives in
[`examples/reference_worker/worker.py`](../examples/reference_worker/worker.py).

## Request

`POST <RAGI_REPAIR_WEBHOOK_URL>` with `Content-Type: application/json` and:

| Header | Value |
|---|---|
| `X-Ragi-Event` | `repair.requested` (reindex phase) or `cleanup.requested` |
| `X-Ragi-Timestamp` | unix seconds |
| `X-Ragi-Signature` | `sha256=` + hex HMAC-SHA256 of `"<timestamp>.<raw body bytes>"` with `RAGI_REPAIR_WEBHOOK_SECRET` |
| `X-Ragi-Delivery` | unique id (use for idempotency) |

Verify the signature over the **raw** bytes, compare in constant time, and reject timestamps older than ~5 minutes.

```python
import hmac, hashlib, time
def verify(secret, ts, sig, body: bytes) -> bool:
    if abs(time.time() - float(ts)) > 300: return False
    mac = hmac.new(secret.encode(), ts.encode() + b"." + body, hashlib.sha256).hexdigest()
    return hmac.compare_digest("sha256=" + mac, sig)
```

## Phase 1 - `reindex` (add / replace only)

```json
{
  "event": "repair.requested", "phase": "reindex", "plan_id": "…", "created_at": "…",
  "callback_url": "https://ragi.example.com/api/repairs/<plan_id>/callback",
  "safety": {"delete_policy": "never_before_verified", "note": "…"},
  "target_fingerprint": {"chunking_version": "recursive-v2", "embedding_model": "…", "embedding_dim": 1536},
  "items": [
    {"tenant_id": "acme", "document_id": "policies/leave.pdf", "source_uri": "s3://bucket/acme/policies/leave.pdf",
     "source_version": "…", "source_hash": "…", "expected_chunk_count": 7,
     "actions": ["reindex_full"], "missing_chunks": [], "issue_ids": ["…"]}
  ]
}
```

For each item: re-read the **latest** source, parse -> chunk -> embed, and upsert with **deterministic point ids**
(so a retry overwrites instead of duplicating), then update your manifest (`source_hash`, counts, `indexed_version`,
fingerprint, status). Actions: `reindex_full`, `reindex_chunks` (only `missing_chunks` are required, a full rebuild is also fine),
`fix_metadata` (correct the manifest/payload; no re-embedding). **Do not delete vectors in this phase.**

Respond `2xx` quickly and work asynchronously. When finished, optionally `POST callback_url` with the same signature scheme so
verification starts immediately; otherwise an operator clicks *Verify* (or schedule `POST /api/repairs/{id}/verify`).

## Verification (done by the platform, not trusted from your worker)

Per document, after a scoped re-audit: all expected chunks present · embeddings present · latest version indexed · metadata
correct · old vectors inactive. Documents that fail keep their old vectors and stay in the plan (status `failed`);
re-trigger sends only the failed documents.

## Phase 2 - `cleanup` (explicit deletions)

Only after documents pass verification **and** an operator approves (`RAGI_CLEANUP_POLICY=manual`, the default;
`auto` removes after verification). The platform re-computes the list from the live index at that moment:

```json
{
  "event": "cleanup.requested", "phase": "cleanup", "plan_id": "…",
  "cleanup": [
    {"tenant_id": "acme", "document_id": "policies/old.pdf", "collection": "kb_main",
     "reason": "orphan_vector", "point_ids": ["…", "…"]}
  ]
}
```

Delete exactly those point ids (in your own tool, with your own policy: soft-delete, snapshot first, ...). For a document
that no longer exists, also retire its manifest rows, otherwise the audit will flag a `manifest_orphan`.
`reason` is one of `superseded_active`, `duplicate_chunk`, `orphan_vector`, `tenant_mismatch`.

## Preview without sending

`GET /api/repairs/{id}/payload` returns the reindex payload that *would* be sent. With no webhook configured you can export the plan
this way and run it however you like.
