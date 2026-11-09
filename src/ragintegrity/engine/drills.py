"""Drills: show the detector catching a fault on a customer's own document without touching anything.

A drill reads one real document exactly as an audit does, then pretends *in memory* that something went wrong, and runs the
normal reconciliation on that pretend picture. Nothing is written to S3, the database or the vector index, nothing is saved
as an issue, and no alert is sent.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import replace
from typing import Any

from ..models import DocKey, IndexedChunk, IssueType, Scope
from .audit import AuditOptions, _config, collect
from .reconcile import reconcile

DRILL_TENANT = "drill-other-tenant"


class _MislabelledIndex:
    """A real index that reports one document's vectors under a different tenant. Read-only: only ``scan`` is changed."""

    def __init__(self, inner: Any, key: DocKey, default_tenant: str) -> None:
        self.inner, self.key, self.default_tenant = inner, key, default_tenant

    def scan(self, scope: Scope | None = None, with_vectors: bool = False) -> Iterator[IndexedChunk]:
        for chunk in self.inner.scan(scope, with_vectors):
            if (chunk.tenant_id or self.default_tenant, chunk.document_id) == self.key:
                yield replace(chunk, tenant_id=DRILL_TENANT)
            else:
                yield chunk

    @property
    def deadline(self) -> float | None:  # the audit hands its time budget to the real connector underneath
        return getattr(self.inner, "deadline", None)

    @deadline.setter
    def deadline(self, value: float | None) -> None:
        if hasattr(self.inner, "deadline"):
            self.inner.deadline = value

    def __getattr__(self, name: str) -> Any:
        return getattr(self.inner, name)


def drill_tenant_mismatch(source: Any, manifest: Any, index: Any, opts: AuditOptions, key: DocKey) -> dict[str, Any]:
    """Pretend every vector of ``key`` is labelled with another tenant, and report what the audit would raise."""
    opts = replace(opts, probe=False, progress=None)  # the pretend tenant has no real vectors to search, so no live probe
    scope = Scope(keys=frozenset({key}))
    wrapped = _MislabelledIndex(index, key, opts.default_tenant)
    c = collect(source, manifest, wrapped, opts, scope)
    # evaluate everything that was collected: the relabelled vectors sit under a tenant outside the one-document scope
    result = reconcile(c.source, c.manifest, c.chunk_rows, c.agg, _config(index, opts, c.required), None)
    moved = c.agg.states.get((DRILL_TENANT, key[1]))
    findings = [{"type": f.type.value, "severity": f.severity.value, "tenant_id": f.tenant_id, "document_id": f.document_id,
                 "title": f.title, "detail": f.detail} for f in result.findings]
    caught = any(f.type == IssueType.TENANT_MISMATCH for f in result.findings)
    leak = next((f for f in result.findings if f.type == IssueType.TENANT_MISMATCH), None)
    return {
        "drill": True,
        "document": {"tenant_id": key[0], "document_id": key[1], "points": moved.point_count if moved else 0},
        "simulated": (f"In memory only, all {moved.point_count if moved else 0} vector(s) of this document were relabelled to a "
                      f"different tenant ('{DRILL_TENANT}')."),
        "caught": caught,
        "findings": findings,
        "would_alert": ({"severity": leak.severity.value, "text": f"RAGGuard: 1 critical issue. {leak.title}: document "
                                                                  f"{key[1]} (tenant {key[0]})."} if leak else None),
        "nothing_changed": "This was a read-only drill. Nothing was written to your S3, database or vector index, saved as an "
                           "issue, or sent as an alert.",
    }
