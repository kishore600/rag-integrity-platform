"""Safe repair workflow: plan -> trigger the customer's worker -> verify -> (approved) cleanup -> verify.

The platform never writes to or deletes from the customer's systems. It asks the customer's own
ingestion worker (through a signed webhook) to do the work, then independently verifies the result.
Superseded vectors are only handed over for removal after the replacements have been verified, and
only after an operator approves (RAGI_CLEANUP_POLICY=manual, the default).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

import httpx

from .engine.planning import estimate_workload, plan_items
from .models import CLEANUP_TYPES, IssueType, Scope

if TYPE_CHECKING:
    from .service import IntegrityService

REINDEX_CHECKS = ("expected_chunks_present", "embeddings_present", "latest_version_indexed", "metadata_correct")
SIGNATURE_TOLERANCE_S = 300


class RepairError(RuntimeError):
    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


def sign(secret: str, timestamp: str, body: bytes) -> str:
    mac = hmac.new(secret.encode(), timestamp.encode() + b"." + body, hashlib.sha256)
    return "sha256=" + mac.hexdigest()


def verify_signature(secret: str, timestamp: str, body: bytes, signature: str) -> bool:
    try:
        if abs(time.time() - float(timestamp)) > SIGNATURE_TOLERANCE_S:
            return False
    except (TypeError, ValueError):
        return False
    return hmac.compare_digest(sign(secret, timestamp, body), signature or "")


class RepairManager:
    def __init__(self, service: IntegrityService) -> None:
        self.svc = service

    # ------------------------------------------------------------------ plan
    def create_plan(self, *, issue_ids: list[str] | None = None, min_severity: str | None = None,
                    tenant: str | None = None, types: list[str] | None = None) -> dict[str, Any]:
        svc = self.svc
        issues = svc.ledger.open_issues(ids=issue_ids, min_severity=min_severity)
        if tenant:
            issues = [i for i in issues if i["tenant_id"] == tenant]
        if types:
            issues = [i for i in issues if i["type"] in types]
        keys = sorted({(i["tenant_id"], i["document_id"]) for i in issues if i["document_id"] != "*"})
        if not keys:
            raise RepairError("No open document-level issues match that selection.", 404)
        docs = svc.ledger.documents_for(keys)
        items = plan_items(issues, docs)
        summary = estimate_workload(
            items, docs, list(svc.ledger.all_documents()), chunk_tokens=svc.settings.chunk_size_tokens,
            price_per_mtok=svc.settings.embedding_price_per_mtok)
        plan_id = str(uuid.uuid4())
        svc.ledger.save_plan(plan_id, "draft", items, summary, create=True)
        svc.ledger.add_repair_event(plan_id, "created", {"documents": len(items), "issues": len(issues)})
        return self.get(plan_id)

    def get(self, plan_id: str) -> dict[str, Any]:
        plan = self.svc.ledger.get_plan(plan_id)
        if plan is None:
            raise RepairError("Repair plan not found.", 404)
        plan["events"] = self.svc.ledger.repair_events(plan_id)
        return plan

    # ------------------------------------------------------------------ payloads / delivery
    def payload(self, plan: dict[str, Any], phase: str, cleanup: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        s = self.svc.settings
        target = s.target_fingerprint()
        body: dict[str, Any] = {
            "event": "repair.requested" if phase == "reindex" else "cleanup.requested",
            "plan_id": plan["id"], "phase": phase,
            "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "safety": {"delete_policy": "never_before_verified",
                       "note": "Reindex phase must only add/replace vectors. Removal is requested separately, after verification."},
        }
        base = self.svc.callback_base or s.public_base_url
        if base and s.repair_webhook_secret:  # a callback is only useful (and only accepted) when it can be signed
            body["callback_url"] = f"{base.rstrip('/')}/api/repairs/{plan['id']}/callback"
        if phase == "reindex":
            body["target_fingerprint"] = target.to_dict() if target else {}
            body["items"] = [
                {k: it.get(k) for k in ("tenant_id", "document_id", "source_uri", "source_version", "source_hash",
                                        "expected_chunk_count", "missing_chunks", "issue_ids")} | {"actions": it["actions"]}
                for it in plan["items"] if it["actions"] and it["status"] in ("planned", "failed")
            ]
        else:
            body["cleanup"] = cleanup or []
        return body

    def _deliver(self, body: dict[str, Any]) -> dict[str, Any]:
        s = self.svc.settings
        url = s.repair_webhook_url or ("demo://worker" if s.is_demo else None)
        if not url:
            raise RepairError("No repair webhook configured. Set RAGI_REPAIR_WEBHOOK_URL (and RAGI_REPAIR_WEBHOOK_SECRET) "
                              "to hand repairs to your ingestion worker, or export the plan from GET /api/repairs/{id}/payload.")
        if url.startswith("demo://"):
            world = self.svc.connectors.world
            if world is None:
                raise RepairError("demo://worker is only available in demo mode.")
            return world.run_worker(json.loads(json.dumps(body)))
        if not s.repair_webhook_secret:
            raise RepairError("RAGI_REPAIR_WEBHOOK_SECRET must be set before payloads are sent to a real webhook.")
        raw = json.dumps(body, separators=(",", ":"), sort_keys=True).encode()
        ts = str(int(time.time()))
        headers = {"Content-Type": "application/json", "X-Ragi-Event": body["event"], "X-Ragi-Timestamp": ts,
                   "X-Ragi-Delivery": str(uuid.uuid4()), "X-Ragi-Signature": sign(s.repair_webhook_secret, ts, raw)}
        try:
            resp = httpx.post(url, content=raw, headers=headers, timeout=30)
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise RepairError(f"Repair webhook delivery failed: {type(exc).__name__}: {str(exc)[:200]}", 502) from exc
        try:
            return resp.json()
        except ValueError:
            return {"accepted": True}

    # ------------------------------------------------------------------ trigger / verify / cleanup
    def trigger(self, plan_id: str) -> dict[str, Any]:
        plan = self.get(plan_id)
        if plan["status"] not in ("draft", "partial", "failed"):
            raise RepairError(f"Plan is '{plan['status']}'; only draft, partial or failed plans can be (re)triggered.", 409)
        body = self.payload(plan, "reindex")
        if not body["items"]:
            raise RepairError("This plan has nothing to reprocess (cleanup only). Use approve-cleanup.", 409)
        resp = self._deliver(body)
        self.svc.ledger.save_plan(plan_id, "triggered", plan["items"], plan["summary"])
        self.svc.ledger.add_repair_event(plan_id, "reindex_triggered", {"documents": len(body["items"]), "worker_response": resp})
        return self.get(plan_id)

    def verify(self, plan_id: str) -> dict[str, Any]:
        plan = self.get(plan_id)
        if plan["status"] == "draft":
            raise RepairError("Trigger the plan before verifying it.", 409)
        items = plan["items"]
        keys = frozenset((i["tenant_id"], i["document_id"]) for i in items)
        result = self.svc.run_audit(scope=Scope(keys=keys), trigger="repair-verify", kind="verify", probe=False)
        types_by_key: dict[tuple[str, str], set[str]] = {}
        for f in result.findings:
            types_by_key.setdefault(f.key, set()).add(f.type.value)

        for it in items:
            found = types_by_key.get((it["tenant_id"], it["document_id"]), set())
            checks = {
                "expected_chunks_present": not (found & {IssueType.MISSING_EMBEDDING.value, IssueType.PARTIAL_INDEX.value}),
                "embeddings_present": not (found & {IssueType.EMPTY_EMBEDDING.value, IssueType.MISSING_EMBEDDING.value}),
                "latest_version_indexed": IssueType.STALE_EMBEDDING.value not in found,
                "metadata_correct": not (found & {IssueType.METADATA_INCONSISTENT.value, IssueType.PIPELINE_DRIFT.value}),
                "old_vectors_inactive": not (found & CLEANUP_TYPES),
            }
            it["checks"], it["remaining_types"] = checks, sorted(found)
            reindex_ok = all(checks[c] for c in REINDEX_CHECKS)
            if all(checks.values()):
                it["status"] = "completed"
            elif reindex_ok and it["actions"]:
                it["status"] = "reindexed"  # new generation verified; superseded vectors await cleanup
            elif reindex_ok and not it["actions"]:
                it["status"] = "awaiting_cleanup"
            else:
                it["status"] = "failed"

        statuses = {it["status"] for it in items}
        if statuses == {"completed"}:
            new_status = "completed"
        elif statuses <= {"completed", "reindexed", "awaiting_cleanup"}:
            new_status = "cleanup_pending"
        elif "failed" in statuses and len(statuses) > 1:
            new_status = "partial"
        else:
            new_status = "failed"

        done = sum(it["status"] == "completed" for it in items)
        failed = sum(it["status"] == "failed" for it in items)
        self.svc.ledger.save_plan(plan_id, new_status, items, plan["summary"])
        self.svc.ledger.add_repair_event(plan_id, "verified", {
            "result": new_status, "completed": done, "failed": failed, "total": len(items),
            "verification_run": result.run_id,
            "failed_documents": [f"{i['tenant_id']}/{i['document_id']}" for i in items if i["status"] == "failed"][:20]})
        if new_status == "cleanup_pending" and self.svc.settings.cleanup_policy == "auto":
            return self.approve_cleanup(plan_id)
        return self.get(plan_id)

    def approve_cleanup(self, plan_id: str) -> dict[str, Any]:
        plan = self.get(plan_id)
        if plan["status"] not in ("cleanup_pending", "partial"):
            raise RepairError(f"Cleanup can only be approved once replacements are verified (plan is '{plan['status']}').", 409)
        items = plan["items"]
        eligible = [it for it in items if it["status"] in ("reindexed", "awaiting_cleanup")]
        if not eligible:
            raise RepairError("Nothing is eligible for cleanup yet: documents must first pass verification.", 409)
        keys = frozenset((i["tenant_id"], i["document_id"]) for i in eligible)
        # recompute the removal list *now*, from the live index, instead of trusting the plan-time list
        result = self.svc.run_audit(scope=Scope(keys=keys), trigger="cleanup-prep", kind="verify", probe=False)
        groups: list[dict[str, Any]] = []
        for f in result.findings:
            if f.type.value in CLEANUP_TYPES and f.key in keys:
                for coll, ids in (f.evidence.get("removal_points") or {}).items():
                    if ids:
                        groups.append({"tenant_id": f.tenant_id, "document_id": f.document_id, "collection": coll,
                                       "reason": f.type.value, "point_ids": ids})
        if not groups:
            raise RepairError("No superseded vectors found any more - run verify again.", 409)
        resp = self._deliver(self.payload(plan, "cleanup", cleanup=groups))
        self.svc.ledger.save_plan(plan_id, "cleanup_triggered", items, plan["summary"])
        self.svc.ledger.add_repair_event(plan_id, "cleanup_triggered", {
            "points": sum(len(g["point_ids"]) for g in groups), "documents": len(keys), "worker_response": resp})
        return self.get(plan_id)

    def handle_callback(self, plan_id: str, body: bytes, timestamp: str, signature: str) -> dict[str, Any]:
        secret = self.svc.settings.repair_webhook_secret
        if not secret or not verify_signature(secret, timestamp, body, signature):
            raise RepairError("Invalid callback signature.", 401)
        self.svc.ledger.add_repair_event(plan_id, "worker_callback", {"body": body[:500].decode(errors="replace")})
        return self.verify(plan_id)
