"""Alerts: tell engineers when new inconsistencies appear (Slack-compatible incoming webhook)."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from .config import Settings
from .ledger import RunDiff
from .models import severity_at_least

log = logging.getLogger("ragintegrity.alerts")


def build_message(settings: Settings, run_id: str, diff: RunDiff, stats: dict[str, Any]) -> dict[str, Any] | None:
    fresh = [*diff.opened, *diff.reopened, *diff.escalated]
    seen: set[str] = set()
    picked = []
    for f in fresh:
        if f.issue_id in seen or not severity_at_least(f.severity.value, settings.alert_min_severity):
            continue
        seen.add(f.issue_id)
        picked.append(f)
    if not picked:
        return None
    picked.sort(key=lambda f: -["info", "low", "medium", "high", "critical"].index(f.severity.value))
    lines = [f"*RAG Integrity*: {len(picked)} new issue(s) at or above `{settings.alert_min_severity}` "
             f"(health {stats.get('health_score')}%)"]
    for f in picked[:10]:
        lines.append(f"• [{f.severity.value.upper()}] {f.title} — `{f.tenant_id}/{f.document_id}`")
    if len(picked) > 10:
        lines.append(f"…and {len(picked) - 10} more")
    return {
        "text": "\n".join(lines),
        "run_id": run_id,
        "summary": {"new_issues": len(picked), "health_score": stats.get("health_score")},
        "issues": [{"id": f.issue_id, "type": f.type.value, "severity": f.severity.value, "tenant_id": f.tenant_id,
                    "document_id": f.document_id, "title": f.title} for f in picked[:25]],
    }


def notify(settings: Settings, run_id: str, diff: RunDiff, stats: dict[str, Any]) -> dict[str, Any]:
    if not settings.alert_webhook_url:
        return {"sent": 0, "reason": "no RAGI_ALERT_WEBHOOK_URL configured"}
    message = build_message(settings, run_id, diff, stats)
    if message is None:
        return {"sent": 0, "reason": "no new issues at or above the alert threshold"}
    try:
        resp = httpx.post(settings.alert_webhook_url, json=message, timeout=10)
        resp.raise_for_status()
        return {"sent": 1, "issues": message["summary"]["new_issues"]}
    except Exception as exc:  # alert delivery must never fail an audit
        log.warning("alert delivery failed: %s", exc)
        return {"sent": 0, "error": f"{type(exc).__name__}: {str(exc)[:160]}"}
