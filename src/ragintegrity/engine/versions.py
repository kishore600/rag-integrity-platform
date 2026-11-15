"""Document version integrity: what the source says the document is, against what the index actually holds.

The engine already raises ``stale_embedding``, ``superseded_active``, ``partial_index`` and ``pipeline_drift``. This module
puts the evidence for ONE document side by side, as the table an engineer would otherwise assemble by hand:

    Property                         Expected   Actual
    Source version                   v3         v2            mismatch
    Chunk count (any revision)       24         24            match
    Chunks of the current revision   24         0             mismatch

so "24 chunks exist, but they belong to an outdated revision" is visible at a glance. A chunk id alone does not say which
revision of the text a vector holds, so the table compares revisions (source version, source hash, chunk hashes), not only ids.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from ..ids import normalize_hash
from ..models import ChunkRow, Fingerprint, ManifestRow, SourceDoc
from .index_state import FRESH, OUTDATED, STALE, UNKNOWN, DocIndexState

TITLES = {
    "in_sync": "In sync",
    "version_mismatch": "Version mismatch",
    "partly_outdated": "Partly outdated",
    "config_changed": "Pipeline configuration changed",
    "unknown_revision": "Revision cannot be verified",
    "not_indexed": "Not indexed",
    "source_missing": "Source document is gone",
}


def _norm(v: Any) -> str:
    return str(v).strip().lower()


def _row(prop: str, expected: Any, actual: Any, status: str) -> dict[str, Any]:
    return {"property": prop, "expected": expected, "actual": actual, "status": status}


def _compare(expected: str | None, actual: Counter | dict[str, int]) -> tuple[str, str]:
    """(display of the actual values, status) for one expected value against what the index holds."""
    values = {k: n for k, n in actual.items() if k not in (None, "")}
    if not values:
        return "not recorded in the index", "unknown"
    shown = ", ".join(f"{k}" if len(values) == 1 else f"{k} ({n} points)" for k, n in sorted(values.items(), key=lambda kv: -kv[1]))
    if expected in (None, ""):
        return shown, "unknown"
    hits = sum(n for k, n in values.items() if _norm(k) == _norm(expected))
    total = sum(values.values())
    return shown, "match" if hits == total else ("mismatch" if hits == 0 else "partial")


def version_check(
    s: SourceDoc | None, m: ManifestRow | None, st: DocIndexState | None, chunk_rows: dict[str, ChunkRow] | None,
    target: Fingerprint | None,
) -> dict[str, Any]:
    """The expected-versus-actual comparison for one document, with a verdict in plain words."""
    classes = st.classes if st else Counter()
    live = classes[FRESH] + classes[UNKNOWN]
    stale, outdated, unknown = classes[STALE], classes[OUTDATED], classes[UNKNOWN]
    present = st.point_count if st else 0
    by_revision = {"current": classes[FRESH], "older_revision": stale, "older_config": outdated, "revision_unknown": unknown}

    all_chunks: set[str] = set()
    live_chunks: set[str] = set()
    if st:
        for (_coll, ck, cls), _slot in st.slots.items():
            all_chunks.add(ck)
            if cls in (FRESH, UNKNOWN):
                live_chunks.add(ck)
    expected_ids = set(chunk_rows) if chunk_rows else set()
    expected_total = len(expected_ids) or (m.expected_chunk_count if m and m.expected_chunk_count else None)

    rows: list[dict[str, Any]] = []
    if s is not None and st is not None and present:
        versions = dict(st.versions) or ({m.indexed_version: present} if m and m.indexed_version else {})
        shown, status = _compare(s.source_version, versions)
        rows.append(_row("Source version", s.source_version, shown, status))
        shown, status = _compare(normalize_hash(s.source_hash), {h: n for h, n in st.hashes.items() if h})
        rows.append(_row("Source hash", s.source_hash, shown, status))
    if expected_total is not None and present:
        rows.append(_row("Chunk count (any revision)", expected_total, len(all_chunks),
                         "match" if len(all_chunks) == expected_total else "mismatch"))
        rows.append(_row("Chunks of the current revision", expected_total, len(live_chunks),
                         "match" if len(live_chunks) == expected_total else "mismatch"))
    if expected_ids and present:
        named = {c for c in all_chunks if not c.startswith(("idx:", "pt:"))}
        found = expected_ids & {c for c in live_chunks if c in named}
        missing = sorted(expected_ids - found)
        unexpected = sorted({c for c in live_chunks if c in named} - expected_ids)
        parts = [f"{len(found)} of {len(expected_ids)} expected found in the current revision"]
        if missing:
            parts.append(f"{len(missing)} missing")
        if unexpected:
            parts.append(f"{len(unexpected)} not in the current version")
        rows.append(_row("Chunk IDs", f"{len(expected_ids)} expected", ", ".join(parts),
                         "match" if not missing and not unexpected else "mismatch"))
    if st and st.chunk_hash_checked:
        good = st.chunk_hash_checked - st.chunk_hash_bad
        rows.append(_row("Chunk hashes", "as recorded by the pipeline", f"{good} of {st.chunk_hash_checked} chunks match",
                         "match" if not st.chunk_hash_bad else ("mismatch" if good == 0 else "partial")))
    if st and present:
        for name in Fingerprint.__dataclass_fields__:
            counts: Counter = Counter()
            for fk, n in st.fp_all.items():
                v = getattr(st.fp_objs[fk], name)
                if v is not None:
                    counts[str(v)] += n
            want = getattr(target, name) if target else None
            if want is None and not counts:
                continue
            if want is None and len(counts) <= 1:
                continue  # nothing to compare it with and nothing varies: not worth a row
            shown, status = _compare(None if want is None else str(want), counts)
            if want is None:
                status = "mismatch" if len(counts) > 1 else "unknown"
                shown = shown + " (varies inside this document)" if len(counts) > 1 else shown
            rows.append(_row(name.replace("_", " ").capitalize(), None if want is None else want, shown, status))

    if s is None:
        rows = []  # nothing to compare an index against

    # ---- the verdict, in the words an engineer would use
    if s is None:
        verdict, why = "source_missing", "The document is no longer in the source."
    elif not present:
        verdict, why = "not_indexed", "There are no vectors for this document in the index."
    elif live == 0 and stale > 0:
        verdict = "version_mismatch"
        why = (f"{len(all_chunks)} chunk(s) exist in the index"
               + (f" ({expected_total} expected)" if expected_total is not None else "")
               + ", but they belong to an outdated revision of the document.")
    elif stale > 0 or (outdated > 0 and live > 0):
        verdict = "partly_outdated"
        bits = []
        if stale:
            bits.append(f"{stale} vectors from an older revision")
        if outdated:
            bits.append(f"{outdated} vectors built with an older pipeline configuration")
        why = "The current revision is indexed, but " + " and ".join(bits) + " are still active."
    elif outdated > 0:
        verdict = "config_changed"
        diff = ", ".join(sorted(st.outdated_conflicts)) if st and st.outdated_conflicts else "the pipeline configuration"
        why = f"The content is current, but {outdated} vectors were built with a different {diff} than the target."
    elif live and unknown == live:
        verdict = "unknown_revision"
        why = ("The index payloads carry no hash or version for this document, so which revision the chunks hold cannot be "
               "verified from the index. Chunk counts and ids are still compared.")
    else:
        verdict, why = "in_sync", "The index holds the current revision of the document."
    if verdict in ("in_sync", "unknown_revision") and any(r["status"] == "mismatch" for r in rows):
        why += " Some details above still disagree."
    return {"verdict": verdict, "title": TITLES[verdict], "explanation": why, "rows": rows, "points_by_revision": by_revision}
