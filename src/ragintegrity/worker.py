"""The background worker: runs queued audits for as long as they take, and carries on after every pause.

``ragi worker`` is a loop that never ends. It looks for an audit that is waiting in the queue (``RAGI_AUDIT_QUEUE``), works on it
and goes back to waiting. An audit that stops part-way (``partial``: time ran out, or the index could not be reached) has its next
stretch queued, and that stretch resumes from the last checkpoint. If the worker dies, its heartbeat stops, the audit becomes
partial and the next stretch is queued, so the next worker carries on from the last checkpoint.

In ``app`` mode one worker serves every workspace; in ``live`` mode it serves the one set of connections from the environment.
"""

from __future__ import annotations

import logging
import os
import socket
import threading
from collections.abc import Callable
from typing import Any

from .config import Settings, get_settings
from .service import IntegrityService

log = logging.getLogger("ragintegrity.worker")


def default_worker_id() -> str:
    return f"{socket.gethostname()}-{os.getpid()}"


class Worker:
    def __init__(self, settings: Settings | None = None, *, worker_id: str | None = None, budget: float | None = None,
                 service: IntegrityService | None = None) -> None:
        self.settings = settings or get_settings()
        self.worker_id = worker_id or default_worker_id()
        self.budget = budget  # seconds of work per stretch; None means until the audit is done
        self._service = service
        self._manager: Any = None

    # ------------------------------------------------------------------ who to work for
    def _live_service(self) -> IntegrityService:
        if self._service is None:
            self._service = IntegrityService(self.settings)
            self._service.ensure_ready()
        return self._service

    def _app_manager(self) -> Any:
        if self._manager is None:
            from .api.app import AppState

            state = AppState(self.settings, None)
            if not state.ensure():
                raise RuntimeError("The multi-user app is not set up: " + "; ".join(state.problems))
            self._manager = state.manager
        return self._manager

    # ------------------------------------------------------------------ one turn
    def run_once(self) -> dict[str, Any] | None:
        """Do one stretch of work on the oldest queued audit. Returns what happened, or None when the queue is empty."""
        if self.settings.is_app:
            manager = self._app_manager()
            manager.ledger.retire_stale_runs(any_workspace=True)  # take back audits whose worker died
            claimed = manager.ledger.claim_run(self.worker_id, any_workspace=True)
            if claimed is None:
                return None
            try:
                out = manager.service(claimed["workspace_id"]).work(self.worker_id, self.budget, run=claimed)
            except Exception as exc:  # the workspace's connections could not even be built: say so on the audit, not nowhere
                manager.ledger.for_workspace(claimed["workspace_id"]).finish_run(
                    claimed["id"], "failed", {}, error=f"{type(exc).__name__}: {str(exc)[:300]}")
                return {"run_id": claimed["id"], "workspace_id": claimed["workspace_id"], "status": "failed", "error": str(exc)[:300]}
            return {**(out or {}), "workspace_id": claimed["workspace_id"]}
        return self._live_service().work(self.worker_id, self.budget)

    def run_forever(self, poll_seconds: float = 10.0, stop: threading.Event | None = None,
                    say: Callable[[str], None] = print) -> None:
        """Work on audits one after another; wait ``poll_seconds`` between looks at an empty queue."""
        stop = stop or threading.Event()
        say(f"worker {self.worker_id} is up ({self.settings.mode} mode). Waiting for audits...")
        while not stop.is_set():
            try:
                out = self.run_once()
            except Exception as exc:  # a broken database or a bad setup must not kill the loop
                log.exception("worker turn failed")
                say(f"worker turn failed: {type(exc).__name__}: {exc}")
                out = None
            if out is None:
                stop.wait(poll_seconds)
            else:
                say(_describe(out))  # a paused audit is simply picked up again on the next turn


def _describe(out: dict[str, Any]) -> str:
    where = f" [{out['workspace_id']}]" if out.get("workspace_id") else ""
    detail = ""
    if out.get("documents_total"):
        detail = f" {out.get('documents_done') or 0:,} of {out['documents_total']:,} documents ({out.get('percent') or 0}%)"
    if out.get("error"):
        detail += f" {out['error']}"
    return f"audit {out['run_id'][:8]}{where}: {out['status']}{detail}"
