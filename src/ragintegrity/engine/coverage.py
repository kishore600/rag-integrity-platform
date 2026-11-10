"""Do the three systems line up? Duplicate-ID warnings for audits, and the setup and coverage check.

A reconciliation is only as good as the ID it matches on. If the file name says ``2329961`` and the manifest says
``bill-2329961``, every document looks "missing" and the audit is noise. The check below reads a bounded, cheap look at
each system (no hashing, no full scan), compares the IDs, and says in plain words what lines up and what does not.

Read-only like everything else: it lists S3 keys, reads the manifest rows and samples Qdrant payloads. It never writes.
"""

from __future__ import annotations

import time
from collections import Counter
from collections.abc import Callable, Iterable
from contextlib import closing
from dataclasses import dataclass, field
from datetime import datetime, timezone
from itertools import islice
from typing import Any, Generic, TypeVar

from ..connectors.base import AuditTimeout, check_deadline
from ..ids import id_kind, loose_id, normalize_id
from ..models import DocKey, Scope

T = TypeVar("T")

# bounds: the check must stay quick on a very large corpus (it says so when a limit was reached)
MAX_SOURCE_OBJECTS = 200_000
MAX_MANIFEST_ROWS = 500_000
INDEX_SAMPLE = 1_000        # points whose ids are looked at
INDEX_LOOKUP_DOCS = 200     # S3 documents looked up in the index one by one
INDEX_LOOKUP_POINTS = 50_000
INDEX_LOOKUP_SECONDS = 40   # a filtered read of a big, unindexed collection is slow: give up on this step after this long
LOOKUP_SAMPLE = 200         # manifest files looked at when the audit does not list the bucket
EXAMPLES = 5
MAX_TRACKED = 200           # duplicate ids remembered with their locations (all are counted)
PER_ID_LOCATIONS = 5
ALIGNED, PARTIAL = 0.8, 0.2  # share of documents that line up by ID: pass at or above ALIGNED, warn at or above PARTIAL, else fail
# (the gaps in a pass are real documents the audit reports one by one; this check is about whether the IDs can be matched at all)


# ---------------------------------------------------------------------------------------------- duplicate ids
class Unique(Generic[T]):
    """A dict of ``(tenant, document) -> item`` that remembers when an id turned up more than once.

    Building such a dict by assignment silently keeps only the last item, so a second file (or manifest row) with the
    same id would hide the first. The last one is still the one kept (results do not change), but the duplicates are counted."""

    def __init__(self, label: Callable[[T], str]) -> None:
        self.items: dict[DocKey, T] = {}
        self._label = label
        self.counts: dict[DocKey, int] = {}  # only ids seen more than once
        self.where: dict[DocKey, list[str]] = {}  # where those copies are, for the first MAX_TRACKED such ids

    def add(self, key: DocKey, item: T) -> None:
        prev = self.items.get(key)
        if prev is not None:
            n = self.counts.get(key)
            if n is None:
                self.counts[key] = 2
                if len(self.where) < MAX_TRACKED:
                    self.where[key] = [self._label(prev)]
            else:
                self.counts[key] = n + 1
            places = self.where.get(key)
            if places is not None and len(places) < PER_ID_LOCATIONS:
                places.append(self._label(item))
        self.items[key] = item

    def restrict(self, keep: Callable[[DocKey], bool]) -> dict[DocKey, T]:
        """Keep only some ids (items and duplicate counts); returns the items."""
        self.items = {k: v for k, v in self.items.items() if keep(k)}
        self.counts = {k: n for k, n in self.counts.items() if keep(k)}
        self.where = {k: w for k, w in self.where.items() if keep(k)}
        return self.items

    @property
    def duplicate_ids(self) -> int:
        return len(self.counts)

    @property
    def extra_copies(self) -> int:
        return sum(self.counts.values()) - len(self.counts)

    def examples(self, n: int = EXAMPLES) -> list[dict[str, Any]]:
        return [{"tenant_id": k[0], "document_id": k[1], "copies": self.counts[k], "found_in": self.where[k]}
                for k in sorted(self.where)[:n]]


def id_warnings(source: Unique | None, manifest: Unique | None, empty_manifest_ids: int = 0,
                names: dict[str, str] | None = None) -> list[dict[str, Any]]:
    """Plain-language warnings about identifiers that make an audit less trustworthy. Empty when everything is fine."""
    n = names or {}
    out: list[dict[str, Any]] = []
    if source is not None and source.duplicate_ids:
        ex = source.examples(1)[0]
        out.append({
            "code": "duplicate_source_ids", "severity": "warning", "count": source.duplicate_ids,
            "title": "Some document IDs belong to more than one file in S3",
            "detail": (f"{source.duplicate_ids:,} document ID(s) are shared by {source.duplicate_ids + source.extra_copies:,} files, so the "
                       f"audit could only look at one file per ID and the others were not checked. For example ID '{ex['document_id']}' "
                       f"is {' and '.join(ex['found_in'][:2])}."),
            "fix": ("Change the key pattern so every file gets its own ID (for example include the folder name in the ID), "
                    "or remove the extra copies. The setup check shows your key pattern next to real file names."),
            "examples": source.examples()})
    if manifest is not None and manifest.duplicate_ids:
        ex = manifest.examples(1)[0]
        col = n.get("manifest_document_id")
        out.append({
            "code": "duplicate_manifest_ids", "severity": "warning", "count": manifest.duplicate_ids,
            "title": "Some document IDs have more than one row in the processing manifest",
            "detail": (f"{manifest.duplicate_ids:,} document ID(s) appear on more than one manifest row"
                       f"{f' (column {col})' if col else ''}, so the audit used only one row per ID. For example ID "
                       f"'{ex['document_id']}' has {ex['copies']} rows."),
            "fix": ("Map a column that is unique per document as the document ID, or remove the old rows left behind when a "
                    "document was processed again."),
            "examples": manifest.examples()})
    if empty_manifest_ids:
        col = n.get("manifest_document_id")
        out.append({
            "code": "empty_manifest_ids", "severity": "warning", "count": empty_manifest_ids,
            "title": "Some manifest rows have no document ID",
            "detail": (f"{empty_manifest_ids:,} manifest row(s) have nothing in the document ID column"
                       f"{f' ({col})' if col else ''}, so they cannot be matched to a file or to vectors and were skipped."),
            "fix": "Check that the column map points at the column that holds the document ID."})
    return out


# ---------------------------------------------------------------------------------------------- what was found
@dataclass
class SetupFacts:
    """What the three systems said, before any judging. Everything is a count, an id or a short example."""

    default_tenant: str = "default"
    names: dict[str, str] = field(default_factory=dict)  # field and setting names to quote in messages
    source_only: bool = False
    lookup_mode: bool = False
    # S3
    source_error: str | None = None
    source: Unique | None = None  # documents found by listing (items are object keys)
    source_objects: int = 0
    source_ignored: int = 0
    ignored_examples: list[str] = field(default_factory=list)
    source_truncated: bool = False
    lookup_asked: int = 0  # lookup mode: manifest files looked for in S3 ...
    lookup_found: int = 0  # ... and found
    lookup_missing: list[str] = field(default_factory=list)
    lookup_docs: set[DocKey] = field(default_factory=set)  # lookup mode: the documents that exist
    # manifest
    manifest_error: str | None = None
    manifest: Unique | None = None
    manifest_rows: int = 0
    manifest_empty_ids: int = 0
    manifest_truncated: bool = False
    manifest_without_uri: int = 0
    manifest_uris: list[str] = field(default_factory=list)
    # index
    index_error: str | None = None
    index_rows: list[dict[str, Any]] = field(default_factory=list)  # {"document_id": raw, "tenant_id": raw}
    index_random: bool = True
    index_approx_points: int | None = None
    lookup_index_asked: int = 0
    lookup_index_found: set[DocKey] = field(default_factory=set)
    lookup_index_error: str | None = None
    lookup_index_asked_keys: list[DocKey] = field(default_factory=list)


def _phase(deadline: float | None, seconds: float) -> float | None:
    """A deadline for one step: never later than the overall one."""
    own = time.monotonic() + seconds
    return own if deadline is None else min(own, deadline)


def collect_setup_facts(source: Any, manifest: Any, index: Any, deadline: float | None, *, default_tenant: str = "default",
                        names: dict[str, str] | None = None, source_only: bool = False, lookup_mode: bool = False,
                        explain: Callable[[BaseException], str] = lambda e: f"{type(e).__name__}: {str(e)[:200]}") -> SetupFacts:
    """Take the bounded, read-only look. A system that cannot be read is recorded as an error, and the rest still run."""
    f = SetupFacts(default_tenant=default_tenant, names=names or {}, source_only=source_only, lookup_mode=lookup_mode)
    for connector in (source, manifest, index):
        if hasattr(connector, "deadline"):
            connector.deadline = deadline

    # ---- the processing manifest
    f.manifest = Unique(lambda r: (r.source_uri or "a row with no source address") + (f" (status: {r.processing_status})" if r.processing_status else ""))
    try:
        with closing(manifest.documents(None)) as rows:
            for r in rows:
                f.manifest_rows += 1
                f.manifest.add(r.key, r)
                if not r.source_uri:
                    f.manifest_without_uri += 1
                elif len(f.manifest_uris) < LOOKUP_SAMPLE:
                    f.manifest_uris.append(r.source_uri)
                if f.manifest_rows % 2000 == 0:
                    check_deadline(deadline, "the processing manifest", f" (after {f.manifest_rows:,} rows)")
                if f.manifest_rows >= MAX_MANIFEST_ROWS:
                    f.manifest_truncated = True
                    break
        f.manifest_empty_ids = getattr(manifest, "empty_ids", 0) or 0
    except Exception as exc:
        f.manifest_error = str(exc) if isinstance(exc, AuditTimeout) else explain(exc)

    # ---- the files in S3
    try:
        if lookup_mode and hasattr(source, "key_from_uri") and hasattr(source, "exists"):
            keys = {}
            for uri in f.manifest_uris:
                k = source.key_from_uri(uri)
                if k is not None and source.parse_key(k) is not None:
                    keys[k] = source.parse_key(k)
            f.lookup_asked = len(keys)
            present = source.exists(sorted(keys)) if keys else set()
            f.lookup_found = len(present)
            f.lookup_missing = sorted(k for k in keys if k not in present)[:EXAMPLES]
            f.lookup_docs = {keys[k] for k in present}
        else:
            f.source = Unique(lambda key: key)
            if hasattr(source, "iter_keys"):
                with closing(source.iter_keys()) as listing:
                    for obj_key, parsed in listing:
                        f.source_objects += 1
                        if parsed is None:
                            f.source_ignored += 1
                            if len(f.ignored_examples) < EXAMPLES:
                                f.ignored_examples.append(obj_key)
                        else:
                            f.source.add(parsed, obj_key)
                        if f.source_objects >= MAX_SOURCE_OBJECTS:
                            f.source_truncated = True
                            break
            else:  # a source without a cheap listing (the demo): its inventory is already in memory
                for d in source.inventory(None):
                    f.source_objects += 1
                    f.source.add(d.key, d.source_uri)
    except Exception as exc:
        f.source_error = str(exc) if isinstance(exc, AuditTimeout) else explain(exc)
        f.source = None

    # ---- the vector index: what does it call its documents?
    try:
        if hasattr(index, "id_sample"):
            s = index.id_sample(INDEX_SAMPLE)
            f.index_rows, f.index_random, f.index_approx_points = s["rows"], s["random"], s.get("approx_points")
        else:  # no sampling support: the first points of a plain scan
            f.index_random = False
            for c in islice(index.scan(None), INDEX_SAMPLE):
                f.index_rows.append({"document_id": c.document_id, "tenant_id": c.tenant_id})
    except Exception as exc:
        f.index_error = str(exc) if isinstance(exc, AuditTimeout) else explain(exc)

    # ---- do the S3 documents have pieces in the index? (a few, looked up by id)
    if f.index_error is None:
        pool = sorted(f.source.items) if f.source is not None else sorted(f.lookup_docs)
        if pool:
            step = max(1, len(pool) // INDEX_LOOKUP_DOCS)
            asked = pool[::step][:INDEX_LOOKUP_DOCS]
            f.lookup_index_asked = len(asked)
            f.lookup_index_asked_keys = asked
            if hasattr(index, "deadline"):
                index.deadline = _phase(deadline, INDEX_LOOKUP_SECONDS)
            try:
                for c in islice(index.scan(Scope(keys=frozenset(asked))), INDEX_LOOKUP_POINTS):
                    if c.document_id:
                        f.lookup_index_found.add((c.tenant_id or default_tenant, c.document_id))
            except Exception as exc:
                f.lookup_index_error = str(exc) if isinstance(exc, AuditTimeout) else explain(exc)
    return f


# ---------------------------------------------------------------------------------------------- judging
def _pct(a: int, b: int) -> int:
    return round(100 * a / b) if b else 0


def _frac(a: int, b: int) -> str:
    return f"{a:,} of {b:,} ({_pct(a, b)}%)"


def _verdict(a: int, b: int) -> str:
    share = a / b if b else 0
    return "pass" if share >= ALIGNED else "warn" if share >= PARTIAL else "fail"


def _check(cid: str, name: str, status: str, detail: str, fix: str | None = None, examples: list[str] | None = None,
           hint: str | None = None, numbers: dict[str, Any] | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {"id": cid, "name": name, "status": status, "detail": detail}
    for k, v in (("fix", fix), ("examples", examples), ("hint", hint), ("numbers", numbers)):
        if v:
            out[k] = v
    return out


def _quote(ids: Iterable[str]) -> str:
    return ", ".join(f"'{i}'" for i in ids)


def near_matches(unmatched: list[str], pool: Iterable[str], limit: int = 1000) -> list[tuple[str, str]]:
    """Pairs of ids that differ only by letter case, spaces or leading zeros: they do not match today, but people mean them to."""
    loose: dict[str, str] = {}
    for p in pool:
        loose.setdefault(loose_id(p), p)
    out = []
    for u in unmatched[:limit]:
        m = loose.get(loose_id(u))
        if m is not None and m != u:
            out.append((u, m))
    return out


def containing_pairs(unmatched: list[str], pool: list[str], limit: int = 100, pool_limit: int = 20_000) -> list[tuple[str, str]]:
    """Pairs where one id contains the other (``bill-2329961`` and ``2329961``): usually a prefix or suffix added on one side."""
    out = []
    candidates = pool[:pool_limit]
    for u in unmatched[:limit]:
        for m in candidates:
            short, long_ = (u, m) if len(u) <= len(m) else (m, u)
            if len(short) >= 3 and short != long_ and short in long_:
                out.append((u, m))
                break
    return out


def _join_hint(pairs: list[tuple[str, str]], left: str, right: str, why: str) -> str | None:
    if not pairs:
        return None
    shown = "; ".join(f"{left} '{a}' and {right} '{b}'" for a, b in pairs[:3])
    return f"{len(pairs):,} look like the same document written differently ({shown}). {why}"


CLEAN_UP_NOTE = ("RAGGuard compares IDs exactly. An ID clean-up rule is not available yet: make both sides write the ID the same "
                 "way, or change the key pattern.")


def build_setup_report(f: SetupFacts, duration_seconds: float | None = None) -> dict[str, Any]:
    """Turn the facts into a report: checks (pass / warn / fail / na), coverage numbers, examples and the next steps."""
    names = f.names
    pdoc = names.get("payload_document_id", "document_id")
    checks: list[dict[str, Any]] = []
    limits: list[str] = []

    listing_ok = f.source is not None and f.source_error is None
    manifest_ok = f.manifest is not None and f.manifest_error is None
    src_keys: set[DocKey] = set(f.source.items) if listing_ok and f.source is not None else set()
    man_keys: set[DocKey] = set(f.manifest.items) if manifest_ok and f.manifest is not None else set()
    multi_tenant = len({k[0] for k in (*src_keys, *man_keys)}) > 1

    def label(key: DocKey) -> str:
        return f"{key[0]}/{key[1]}" if multi_tenant else key[1]

    if f.source_truncated:
        limits.append(f"Only the first {MAX_SOURCE_OBJECTS:,} files of the bucket were listed, so the S3 numbers are a lower bound.")
    if f.manifest_truncated:
        limits.append(f"Only the first {MAX_MANIFEST_ROWS:,} manifest rows were read, so the manifest numbers are a lower bound.")
    if f.index_rows and not f.index_random:
        limits.append("This Qdrant server cannot sample at random, so the first points of each collection were used.")
    partial = bool(f.source_truncated or f.manifest_truncated)

    # ---- 1. files in S3
    if f.lookup_mode:
        checks.append(_check("source_files", "Files in S3", "na",
                             "Your setting 'Look up files from the manifest' is on, so audits do not list the bucket. "
                             "The check looks up a sample of the files the manifest names instead (next check)."))
    elif f.source_error:
        checks.append(_check("source_files", "Files in S3", "fail", f"Could not read the bucket: {f.source_error}",
                             "Fix the S3 connection in Settings, then run this check again."))
    elif f.source_objects == 0:
        checks.append(_check("source_files", "Files in S3", "fail", "No files were found under this bucket and key prefix.",
                             "Check the bucket name and the key prefix in Settings."))
    elif not src_keys:
        checks.append(_check("source_files", "Files in S3", "fail",
                             f"{f.source_objects:,} file(s) were found, but none of their names match the key pattern, so no document has an ID.",
                             "Change the key pattern so it captures the document ID from your file names.",
                             examples=f.ignored_examples,
                             hint=f"The pattern is {names['key_pattern']}" if names.get("key_pattern") else None))
    else:
        ignored_share = f.source_ignored / f.source_objects
        mostly_skipped = ignored_share > 0.5  # a pattern that picks some of the files is normal; one that misses most of them is a mistake
        detail = (f"{f.source_objects:,} file(s) listed; {len(src_keys):,} document ID(s) read from their names"
                  + ("." if not f.source_ignored else f"; {f.source_ignored:,} file(s) do not match the key pattern and are skipped"
                     + (". That is fine if the pattern is meant to select only some of the files." if not mostly_skipped else ".")))
        checks.append(_check("source_files", "Files in S3", "warn" if mostly_skipped else "pass", detail,
                             "Most files do not match the key pattern: make it cover them (or move the others out of the prefix)." if mostly_skipped else None,
                             examples=f.ignored_examples if f.source_ignored else None))

    # ---- 2. unique ids in S3
    if listing_ok and f.source is not None and src_keys:
        d = f.source
        if d.duplicate_ids:
            status = "fail" if d.duplicate_ids / len(src_keys) >= 0.05 else "warn"
            ex = d.examples(1)[0]
            checks.append(_check(
                "source_ids_unique", "One file per document ID", status,
                f"{d.duplicate_ids:,} document ID(s) are used by more than one file ({d.duplicate_ids + d.extra_copies:,} files), "
                f"for example '{ex['document_id']}' is {' and '.join(ex['found_in'][:2])}. The audit can only follow one file per ID.",
                "Change the key pattern so every file gets its own ID, or remove the extra copies.",
                examples=[f"{e['document_id']}: {', '.join(e['found_in'][:3])}" for e in d.examples()]))
        else:
            checks.append(_check("source_ids_unique", "One file per document ID", "pass", "Every document ID belongs to exactly one file."))

    # ---- 3. the manifest
    if f.manifest_error:
        checks.append(_check("manifest_rows", "Rows in the manifest", "fail", f"Could not read the manifest: {f.manifest_error}",
                             "Fix the manifest connection and the table and column names in Settings, then run this check again."))
    elif f.manifest_rows == 0 and not f.manifest_empty_ids:
        checks.append(_check("manifest_rows", "Rows in the manifest", "fail", "The manifest table has no rows.",
                             "Check the schema and table name in Settings: the table may be a different one."))
    elif not man_keys:
        checks.append(_check("manifest_rows", "Rows in the manifest", "fail",
                             f"All {f.manifest_empty_ids:,} manifest row(s) have an empty document ID.",
                             "Map the column that holds the document ID (the column map in Settings)."))
    else:
        problems = []
        if f.manifest_empty_ids:
            problems.append(f"{f.manifest_empty_ids:,} row(s) have no document ID and are skipped")
        checks.append(_check("manifest_rows", "Rows in the manifest", "warn" if f.manifest_empty_ids else "pass",
                             f"{f.manifest_rows:,} row(s); {len(man_keys):,} document ID(s)" + (f"; {'; '.join(problems)}." if problems else "."),
                             "Check that the column map points at the column that holds the document ID." if problems else None))
    if manifest_ok and f.manifest is not None and man_keys:
        d = f.manifest
        if d.duplicate_ids:
            status = "fail" if d.duplicate_ids / len(man_keys) >= 0.05 else "warn"
            ex = d.examples(1)[0]
            checks.append(_check(
                "manifest_ids_unique", "One manifest row per document ID", status,
                f"{d.duplicate_ids:,} document ID(s) have more than one manifest row, for example '{ex['document_id']}' has {ex['copies']}. "
                "The audit can only follow one row per ID.",
                "Map a column that is unique per document, or remove the old rows left behind when a document was processed again.",
                examples=[f"{e['document_id']} ({e['copies']} rows)" for e in d.examples()]))
        else:
            checks.append(_check("manifest_ids_unique", "One manifest row per document ID", "pass", "Every document ID has exactly one manifest row."))

    # ---- 4. S3 against the manifest
    src_in_man = len(src_keys & man_keys)
    man_in_src = len(man_keys & src_keys)
    if listing_ok and manifest_ok and src_keys and man_keys:
        unmatched_src = sorted(k[1] for k in src_keys - man_keys)
        unmatched_man = sorted(k[1] for k in man_keys - src_keys)
        status = _verdict(src_in_man, len(src_keys))
        by_id = len({k[1] for k in src_keys} & {k[1] for k in man_keys})
        detail = f"{_frac(src_in_man, len(src_keys))} of the documents in S3 have a manifest row with the same ID."
        fix = hint = None
        examples: list[str] | None = None
        if status != "pass":
            examples = [f"in S3 only: {_quote(unmatched_src[:EXAMPLES])}", f"in the manifest only: {_quote(unmatched_man[:EXAMPLES])}"]
            if by_id > src_in_man:
                fix = ("The same IDs exist on both sides but under different tenant names: see the tenant check below.")
            else:
                near = near_matches(unmatched_src, unmatched_man)
                inside = containing_pairs(unmatched_src, unmatched_man) if not near else []
                hint = (_join_hint(near, "S3", "manifest", CLEAN_UP_NOTE) or
                        _join_hint(inside, "S3", "manifest", "One side has an extra prefix or suffix. " + CLEAN_UP_NOTE))
                fix = ("Make the two sides use the same ID: change the key pattern so it captures the ID the manifest uses, or "
                       "map a different manifest column as the document ID.")
        if partial and status != "pass":
            detail += " (The lists were cut short, so some of these may only be outside the part that was read.)"
        checks.append(_check("source_vs_manifest", "S3 against the manifest", status, detail, fix, examples, hint,
                             {"matched": src_in_man, "of": len(src_keys)}))
        if man_keys:
            ms = _verdict(man_in_src, len(man_keys))
            if f.source_only and ms != "pass":
                ms = "pass"
            msg = f"{_frac(man_in_src, len(man_keys))} of the manifest's documents have a file in S3."
            if ms != "pass":
                msg += " The rest are rows for files that are not in this bucket and prefix (deleted files, or another source)."
                ms = "warn"
            elif f.source_only and man_in_src < len(man_keys) * ALIGNED:
                msg += " Your setting 'Only audit documents found in the source (S3)' is on, so the other rows are ignored."
            checks.append(_check("manifest_vs_source", "Manifest against S3", ms, msg,
                                 "Turn on 'Only audit documents found in the source (S3)' in Settings so those rows are ignored."
                                 if ms == "warn" and not f.source_only else None,
                                 numbers={"matched": man_in_src, "of": len(man_keys)}))

    # ---- 4b. lookup mode: do the files the manifest names exist?
    if f.lookup_mode:
        if f.manifest_error:
            pass
        elif f.lookup_asked == 0:
            checks.append(_check("manifest_files_exist", "Files the manifest names", "fail",
                                 "None of the manifest's source addresses points at a file in this bucket that matches the key pattern.",
                                 "Map the manifest column that holds the S3 address as the source URI, and check the bucket name and key pattern.",
                                 hint=f"{f.manifest_without_uri:,} manifest row(s) have no source address." if f.manifest_without_uri else None))
        else:
            st = _verdict(f.lookup_found, f.lookup_asked)
            checks.append(_check("manifest_files_exist", "Files the manifest names", st,
                                 f"{_frac(f.lookup_found, f.lookup_asked)} of a sample of the manifest's files exist in S3.",
                                 "Check the bucket name, the key prefix and the source URI column." if st != "pass" else None,
                                 examples=f.lookup_missing or None, numbers={"matched": f.lookup_found, "of": f.lookup_asked}))
        checks.append(_check("lookup_blind_spot", "Files without a manifest row", "warn",
                             "'Look up files from the manifest' is on: the audit only sees files the manifest names, so a file in S3 that "
                             "never got a manifest row is not reported.",
                             "Turn that setting off if the bucket is small enough to list (a few thousand files is fine)."))

    # ---- 5. tenants: documents are matched on (tenant, document id), so the tenant names have to agree
    index_docs: list[tuple[DocKey, Any]] = []
    for r in f.index_rows:
        raw = r.get("document_id")
        if raw not in (None, ""):
            index_docs.append(((normalize_id(r.get("tenant_id")) or f.default_tenant, normalize_id(raw) or ""), raw))
    side_keys: dict[str, set[DocKey]] = {"S3": src_keys or set(f.lookup_docs), "manifest": man_keys, "index": {k for k, _ in index_docs}}
    side_keys = {side: ks for side, ks in side_keys.items() if ks}
    if len(side_keys) >= 2:
        label_sets = {side: {k[0] for k in ks} for side, ks in side_keys.items()}
        shown = "; ".join(f"{side}: {_quote(sorted(s)[:4])}{' …' if len(s) > 4 else ''}" for side, s in label_sets.items())
        sides = list(side_keys)
        pairs = [(a, b) for i, a in enumerate(sides) for b in sides[i + 1:]]
        disjoint = [(a, b) for a, b in pairs if not label_sets[a] & label_sets[b]]  # no tenant name in common: nothing can match
        if disjoint:
            a, b = disjoint[0]
            same_ids = len({k[1] for k in side_keys[a]} & {k[1] for k in side_keys[b]}) > len(side_keys[a] & side_keys[b])
            checks.append(_check(
                "tenant_labels", "Tenant names agree", "fail",
                f"{a} and {b} share no tenant name, so their documents cannot be matched. {shown}.",
                "Documents are matched on (tenant, document ID), so the tenant names must agree. Map the tenant column and payload field, "
                "or set the default tenant name so a side without tenants uses the same one.",
                hint=f"The same document IDs exist in {a} and {b}, only under different tenant names." if same_ids else None))
        else:
            checks.append(_check("tenant_labels", "Tenant names agree", "pass",
                                 f"The sides share their tenant names. {shown}." if len(set(map(frozenset, label_sets.values()))) > 1
                                 else f"All sides use the same tenant name(s): {_quote(sorted(next(iter(label_sets.values())))[:4])}."))

    # ---- 6. what the index calls its documents
    rows = f.index_rows
    idx_docs = index_docs
    kinds = Counter(id_kind(raw) for _, raw in idx_docs)
    if f.index_error:
        checks.append(_check("index_ids", "Document IDs in Qdrant", "fail", f"Could not read Qdrant: {f.index_error}",
                             "Fix the Qdrant connection in Settings, then run this check again."))
    elif not rows:
        checks.append(_check("index_ids", "Document IDs in Qdrant", "fail", "The collection(s) are empty: there are no vectors to check.",
                             "Check the collection name in Settings."))
    elif not idx_docs:
        checks.append(_check("index_ids", "Document IDs in Qdrant", "fail",
                             f"None of {len(rows):,} sampled points has a value in the payload field '{pdoc}', so no vector can be tied to a document.",
                             "Set the payload map so document_id points at the field that holds the document ID."))
    else:
        share = len(idx_docs) / len(rows)
        parts = []
        if kinds.get("integer"):
            parts.append(f"{kinds['integer']:,} stored as numbers")
        if kinds.get("digits") or kinds.get("text"):
            parts.append(f"{kinds.get('digits', 0) + kinds.get('text', 0):,} stored as text")
        if kinds.get("decimal"):
            parts.append(f"{kinds['decimal']:,} stored as decimal numbers")
        detail = (f"{_frac(len(idx_docs), len(rows))} of the sampled points carry a document ID in '{pdoc}'"
                  f" ({', '.join(parts)}). A number and the same number written as text are treated as the same ID.")
        status, fix = "pass", None
        if share < ALIGNED:
            status, fix = "warn", f"Some points have no '{pdoc}': they cannot be tied to a document. Check how those points were written."
        if kinds.get("decimal"):
            status = "warn"
            detail += (" Decimal numbers such as 2329961.0 are read as 2329961, but Qdrant cannot filter by them, so "
                       "'Only audit documents found in the source (S3)' would not find those pieces.")
            fix = "Store document IDs as text or whole numbers in Qdrant, or turn that setting off."
        if len([k for k, n in kinds.items() if n and k in ("integer", "decimal")]) and (kinds.get("digits") or kinds.get("text")):
            status = "warn" if status == "pass" else status
            detail += " Both numbers and text are used for IDs in the same collection: that is usually a sign of two writers."
        checks.append(_check("index_ids", "Document IDs in Qdrant", status, detail, fix,
                             examples=[_quote(sorted({str(raw) for _, raw in idx_docs})[:EXAMPLES])]))

        # ---- 7. S3 documents against the index
        if f.lookup_index_asked and (listing_ok or f.lookup_mode) and f.lookup_index_error:
            checks.append(_check("source_vs_index", "S3 against Qdrant", "warn",
                                 f"Looking up S3 documents in Qdrant did not finish: {f.lookup_index_error}",
                                 "Ask the owner of the Qdrant cluster to create a keyword index on the document ID field, then run the check again."))
        elif f.lookup_index_asked:
            found = len({k for k in f.lookup_index_asked_keys if k in f.lookup_index_found})
            st = _verdict(found, f.lookup_index_asked)
            missing = sorted(k[1] for k in f.lookup_index_asked_keys if k not in f.lookup_index_found)
            detail = (f"{_frac(found, f.lookup_index_asked)} of a sample of S3 documents have pieces in Qdrant under the same ID."
                      + (" The rest may simply not be indexed yet." if st == "pass" else ""))
            fix = hint = None
            ex = None
            if st != "pass":
                ex = [f"not found in Qdrant: {_quote(missing[:EXAMPLES])}", f"IDs Qdrant uses: {_quote(sorted({str(r) for _, r in idx_docs})[:EXAMPLES])}"]
                near = near_matches(missing, {k[1] for k, _ in idx_docs})
                inside = containing_pairs(missing, sorted({k[1] for k, _ in idx_docs})) if not near else []
                hint = _join_hint(near, "S3", "Qdrant", CLEAN_UP_NOTE) or _join_hint(inside, "S3", "Qdrant", "One side has an extra prefix or suffix. " + CLEAN_UP_NOTE)
                fix = (f"Most S3 documents have no pieces under their ID. Either they were never indexed, or the index writes a different ID: "
                       f"check the payload field '{pdoc}' and the key pattern." if st == "fail" else
                       "Some S3 documents have no pieces under their ID: they may not be indexed yet, or the index may write a different ID "
                       "for some of them. A full audit lists each one.")
            checks.append(_check("source_vs_index", "S3 against Qdrant", st, detail, fix, ex, hint,
                                 {"matched": found, "of": f.lookup_index_asked}))

        # ---- 8. the index against S3
        known = src_keys | man_keys | f.lookup_docs
        if known and idx_docs:
            in_known = sum(1 for k, _ in idx_docs if k in known)
            out = sorted({k[1] for k, _ in idx_docs if k not in known})
            st = _verdict(in_known, len(idx_docs))
            detail = f"{_frac(in_known, len(idx_docs))} of the sampled points belong to a document that is in S3 or the manifest."
            fix = None
            if st != "pass":
                detail += " The others belong to documents these two do not know (other sources, or documents that were deleted)."
                if f.source_only:
                    detail += " Your setting 'Only audit documents found in the source (S3)' is on, so they are ignored."
                    st = "pass"
                else:
                    fix = "If the index also holds other sources, turn on 'Only audit documents found in the source (S3)' so they are ignored."
                    st = "warn"
            if f.index_approx_points:
                detail += f" (The collection holds about {f.index_approx_points:,} points.)"
            checks.append(_check("index_vs_source", "Qdrant against S3", st, detail, fix,
                                 examples=[f"not in S3 or the manifest: {_quote(out[:EXAMPLES])}"] if out and st != "pass" or (out and f.source_only) else None,
                                 numbers={"matched": in_known, "of": len(idx_docs)}))

    # ---- verdict
    fails = [c for c in checks if c["status"] == "fail"]
    warns = [c for c in checks if c["status"] == "warn"]
    link = {
        "source_to_manifest": _link(src_in_man, len(src_keys)) if listing_ok and manifest_ok else None,
        "manifest_to_source": _link(man_in_src, len(man_keys)) if listing_ok and manifest_ok else None,
        "source_to_index": (_link(len({k for k in f.lookup_index_asked_keys if k in f.lookup_index_found}), f.lookup_index_asked)
                            if f.lookup_index_asked and not f.lookup_index_error else None),
    }
    if fails:
        status = "not_ready"
        headline = (f"Not ready yet: {len(fails)} thing(s) to fix before an audit can be trusted. "
                    f"Start with '{fails[0]['name']}'.")
    elif warns:
        status = "needs_attention"
        headline = f"Almost ready: the three systems mostly line up, with {len(warns)} thing(s) worth a look."
    else:
        status = "ready"
        headline = "Ready: the three systems line up, so an audit will compare the right documents."
    return {
        "status": status, "headline": headline,
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "duration_seconds": round(duration_seconds, 1) if duration_seconds is not None else None,
        "checks": checks, "coverage": link,
        "counts": {
            "source_files": f.source_objects if not f.lookup_mode else None,
            "source_documents": len(src_keys) if listing_ok else None,
            "source_files_skipped": f.source_ignored,
            "manifest_rows": f.manifest_rows, "manifest_documents": len(man_keys),
            "index_points_approx": f.index_approx_points, "index_points_sampled": len(rows),
        },
        "id_types_in_index": dict(kinds),
        "ids_at_a_glance": {
            "source": [k[1] for k in sorted(src_keys)[:EXAMPLES]],
            "manifest": [k[1] for k in sorted(man_keys)[:EXAMPLES]],
            "index": sorted({str(raw) for _, raw in idx_docs})[:EXAMPLES],
        },
        "limits": limits,
        "next_steps": [c["fix"] for c in (*fails, *warns) if c.get("fix")],
    }


def _link(matched: int, total: int) -> dict[str, Any]:
    return {"matched": matched, "of": total, "percent": _pct(matched, total)}


def to_text(report: dict[str, Any]) -> str:
    """The report as plain text (the ``ragi setup-check`` command)."""
    icon = {"pass": "OK  ", "warn": "WARN", "fail": "FAIL", "na": "n/a "}
    lines = [report["headline"], ""]
    for c in report["checks"]:
        lines.append(f"[{icon[c['status']]}] {c['name']}: {c['detail']}")
        for e in c.get("examples") or []:
            lines.append(f"        e.g. {e}")
        if c.get("hint"):
            lines.append(f"        note: {c['hint']}")
        if c.get("fix"):
            lines.append(f"        fix : {c['fix']}")
    if report.get("limits"):
        lines += ["", "Limits of this check:"] + [f"  - {x}" for x in report["limits"]]
    return "\n".join(lines)
