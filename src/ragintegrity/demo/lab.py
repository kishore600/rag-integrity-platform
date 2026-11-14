"""The practice lab: documents with every fault planted on purpose, to explore RAGGuard on your own computer.

Two small worlds, both written into *local* S3 (moto), PostgreSQL and Qdrant by ``scripts/seed_lab.py``:

* **Lab A, "the 30 documents".** 27 documents across three tenants where each of the 13 kinds of fault is planted on exactly one
  document (so you know the right answer), plus 3 practice documents whose IDs are written as a number, a decimal and text, and one
  exact duplicate manifest row. Settings are the defaults: a plain ``<tenant>/<document>`` layout.
* **Lab B, "mini bills".** A miniature of a real setup where files live at ``bills/<bill>/<document>.pdf``, the manifest is a table with a
  true/false ``is_indexed`` column, and the vectors only know their bill. It is for practising the *settings* (key pattern, column map,
  payload map, the lookup and source-only switches) and the setup check.

Nothing here is random at run time: the same documents come out every time, and ``lab/WORKBOOK.md`` (generated from this module) lists
what was planted and what RAGGuard should say about it.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Engine

from ..models import DocKey, IssueType, sha256_hex
from .pipeline import build_points, embed, make_text
from .seed import MANIFEST_COLUMNS
from .world import COLLECTION, EXPECTED_TYPES, TARGET_FP, DemoWorld, etag_of

LAB_SEED = 2026
LAB_DOCS_PER_TENANT = 9  # 3 tenants x 9 = 27 documents, plus the 3 numeric-ID documents = 30
LAB_NOW = datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc)  # only used to generate the workbook the same way every time
# Where the lab may write. Seeding DROPS and recreates tables and collections, so anything else is refused.
LOCAL_HOSTS = ("localhost", "127.0.0.1", "::1", "s3", "postgres", "qdrant", "host.docker.internal")

# One of each fault. The order is the order of the workbook.
LAB_PLAN = (
    ("never_embedded", 1), ("false_success", 1), ("stale", 1), ("deleted_with_manifest", 1), ("deleted_no_manifest", 1),
    ("partial", 1), ("duplicate", 1), ("acl_mismatch", 1), ("count_mismatch", 1), ("drift", 1), ("superseded", 1),
    ("empty_embedding", 1), ("tenant_mismatch", 1),
)

# What a person reads: what was planted, what users would notice, and the fix.
SCENARIOS: dict[str, dict[str, str]] = {
    "never_embedded": {
        "title": "Never embedded",
        "planted": "The file is in S3, but the pipeline never processed it: no manifest row and nothing in Qdrant.",
        "users": "Nobody can ever find this document. No error is shown.",
        "fix": "Re-run the document through the pipeline (a repair plan sends it to your worker).",
    },
    "false_success": {
        "title": "Pipeline said success, nothing is indexed",
        "planted": "The manifest says `success` with N chunks indexed, but Qdrant holds nothing for the document.",
        "users": "Dashboards look green, yet the document is invisible. This is the most dangerous case.",
        "fix": "Re-index it, and find out why the pipeline ticks success before the vectors are written.",
    },
    "stale": {
        "title": "Out of date",
        "planted": "The file changed in S3 after it was indexed; the manifest and the vectors describe the old version.",
        "users": "The chatbot answers from an old version of the document.",
        "fix": "Re-index the document so the vectors match the current file.",
    },
    "deleted_with_manifest": {
        "title": "Deleted file, vectors and manifest row remain",
        "planted": "The file was deleted from S3, but its vectors and its manifest row are still there.",
        "users": "The chatbot can still quote a document that no longer exists.",
        "fix": "Remove the leftover vectors (an approved cleanup), then the manifest row.",
    },
    "deleted_no_manifest": {
        "title": "Deleted file, vectors remain",
        "planted": "The file was deleted from S3 and its manifest row is gone, but the vectors are still in Qdrant.",
        "users": "Deleted content stays searchable.",
        "fix": "Remove the leftover vectors (an approved cleanup).",
    },
    "partial": {
        "title": "Half indexed",
        "planted": "The ingest worker died half way: only some of the document's chunks are in Qdrant, while the manifest claims all of them.",
        "users": "Answers about the missing parts are wrong or empty.",
        "fix": "Re-index just the missing chunks.",
    },
    "duplicate": {
        "title": "Duplicate chunks",
        "planted": "A retried job inserted two chunks a second time with new point ids.",
        "users": "The same passage is returned twice and crowds out other results.",
        "fix": "Remove the extra copies (an approved cleanup).",
    },
    "acl_mismatch": {
        "title": "Permissions disagree",
        "planted": "The manifest's permission hash differs from the one on the vectors.",
        "users": "People may see (or be blocked from) a document they should not (or should).",
        "fix": "Fix the permission metadata; no re-embedding is needed.",
    },
    "count_mismatch": {
        "title": "Chunk count disagrees",
        "planted": "The manifest says one more chunk was indexed than Qdrant really holds.",
        "users": "Usually nothing visible, but the records cannot be trusted.",
        "fix": "Correct the manifest (or re-index if chunks are really missing).",
    },
    "drift": {
        "title": "Built with an old pipeline",
        "planted": "The document was indexed with an old parser, chunking and embedding model; the target pipeline is newer.",
        "users": "Search quality is inconsistent, and old and new vectors cannot be compared.",
        "fix": "Re-index with the current pipeline.",
    },
    "superseded": {
        "title": "Old version still searchable",
        "planted": "The document was updated and re-indexed correctly, but the previous version's vectors were never removed.",
        "users": "Old and new text both appear in answers.",
        "fix": "After the new version is verified, remove the old vectors (an approved cleanup).",
    },
    "empty_embedding": {
        "title": "Empty vectors",
        "planted": "Two of the document's points have an all-zero vector, so they can never match a query.",
        "users": "Parts of the document can never be found.",
        "fix": "Re-index the document.",
    },
    "tenant_mismatch": {
        "title": "Another customer's label",
        "planted": "The vectors of one document carry a different tenant's label. The real document then looks missing.",
        "users": "Content can be returned to the wrong customer: a data leak.",
        "fix": "Re-index under the right tenant, then remove the wrongly labelled vectors.",
    },
}

ISSUE_LABELS = {
    IssueType.MISSING_EMBEDDING: "Missing embeddings", IssueType.PARTIAL_INDEX: "Partial index",
    IssueType.STALE_EMBEDDING: "Stale document version", IssueType.SUPERSEDED_ACTIVE: "Superseded vectors active",
    IssueType.ORPHAN_VECTOR: "Orphan vectors", IssueType.DUPLICATE_CHUNK: "Duplicate chunks",
    IssueType.METADATA_INCONSISTENT: "Metadata mismatch", IssueType.PIPELINE_DRIFT: "Pipeline drift",
    IssueType.EMPTY_EMBEDDING: "Empty embeddings", IssueType.TENANT_MISMATCH: "Tenant mismatch",
    IssueType.MANIFEST_ORPHAN: "Orphan manifest row",
}


class LabWorld(DemoWorld):
    """27 documents with exactly one document per fault (a quarter of the demo's size, with a known answer for each)."""

    def __init__(self, now: datetime | None = None) -> None:
        super().__init__(seed=LAB_SEED, docs_per_tenant=LAB_DOCS_PER_TENANT, now=now)

    def _inject_faults(self) -> None:
        pool = sorted(self.sources)
        self.rng.shuffle(pool)
        cursor = 0
        for name, count in LAB_PLAN:
            for key in pool[cursor: cursor + count]:
                getattr(self, f"_fault_{name}")(key)
                types = [t.value for t in EXPECTED_TYPES[name]]
                if name == "tenant_mismatch":
                    self.faults[key] = {"fault": "tenant_mismatch_source", "types": [IssueType.MISSING_EMBEDDING.value]}
                    self.faults[self._mismatch_key] = {"fault": name, "types": types}
                else:
                    self.faults[key] = {"fault": name, "types": types}
            cursor += count


# ---------------------------------------------------------------------------------------------- safety
def assert_local(label: str, host: str | None) -> None:
    """The lab drops and recreates tables and collections: refuse any target that is not on this computer or in the lab's containers."""
    h = (host or "").lower().strip("[]")
    if h not in LOCAL_HOSTS:
        raise SystemExit(f"Refusing to seed {label} at '{host}': the lab only writes to {', '.join(LOCAL_HOSTS)}.")


# ---------------------------------------------------------------------------------------------- Lab A extras (the ID practice documents)
NUMERIC_DOCS: tuple[tuple[str, str, Any, str], ...] = (
    ("acme", "20001", 20001, "the ID is stored in Qdrant as a whole number"),
    ("acme", "20002", 20002.0, "the ID is stored in Qdrant as a decimal (as a spreadsheet or JSON library would write it)"),
    ("acme", "20003", "20003", "the ID is stored in Qdrant as text"),
)
_ACL_NUMERIC = "acl:acme:numeric"


def _manifest_insert(engine: Engine, q: str, row: dict[str, Any]) -> None:
    cols = ", ".join(MANIFEST_COLUMNS)
    vals = ", ".join(f":{k}" for k in MANIFEST_COLUMNS)
    with engine.begin() as c:
        c.execute(text(f"INSERT INTO {q}rag_document_manifest ({cols}) VALUES ({vals})"), row)


def seed_numeric_docs(s3: Any, bucket: str, engine: Engine, qdrant: Any, *, schema: str | None = None,
                      collection: str = COLLECTION, prefix: str = "", now: datetime | None = None) -> int:
    """Three healthy documents whose Qdrant ID is a number, a decimal and text. Healthy only if RAGGuard treats them as one ID each."""
    from qdrant_client import models as qm

    q = f"{schema}." if schema else ""
    stamp = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    acl = sha256_hex(_ACL_NUMERIC)[:16]
    for tenant, doc, typed, _why in NUMERIC_DOCS:
        body = make_text(f"numeric-{doc}", 1)
        h, sv = sha256_hex(body), etag_of(body)
        s3.put_object(Bucket=bucket, Key=f"{prefix}{tenant}/{doc}", Body=body.encode(), Metadata={"sha256": h})
        points, rows = build_points(tenant, doc, body, source_hash=h, source_version=sv, fp=TARGET_FP, acl_hash=acl)
        for p in points:
            p.payload["document_id"] = typed  # the point of this document
        qdrant.upsert(collection, [qm.PointStruct(id=p.point_id, vector=p.vector, payload=p.payload) for p in points])
        fp = TARGET_FP
        _manifest_insert(engine, q, {
            "tenant_id": tenant, "document_id": doc, "source_uri": f"s3://{bucket}/{prefix}{tenant}/{doc}", "source_version": sv,
            "source_hash": h, "parsed_hash": sha256_hex("parsed:" + body), "parser_version": fp.parser_version,
            "chunking_version": fp.chunking_version, "chunk_size": fp.chunk_size, "chunk_overlap": fp.chunk_overlap,
            "embedding_model": fp.embedding_model, "embedding_model_version": None, "embedding_dim": fp.embedding_dim,
            "preprocessing": fp.preprocessing, "expected_chunk_count": len(rows), "indexed_chunk_count": len(rows),
            "indexed_version": sv, "processing_status": "success", "last_verified_at": None, "updated_at": stamp, "acl_hash": acl,
        })
        with engine.begin() as c:
            c.execute(text(f"INSERT INTO {q}rag_chunk_manifest VALUES (:t, :d, :c, :i, :h)"),
                      [{"t": r.tenant_id, "d": r.document_id, "c": r.chunk_id, "i": r.chunk_index, "h": r.chunk_hash} for r in rows])
    return len(NUMERIC_DOCS)


def duplicate_row_target(world: DemoWorld) -> DocKey:
    """A healthy document of the first tenant: its manifest row gets an exact copy."""
    return next(k for k in sorted(world.sources) if k not in world.faults and k[0] == world.tenants[0])


def seed_duplicate_manifest_row(engine: Engine, key: DocKey, *, schema: str | None = None) -> None:
    """Give one manifest row an exact copy (RAGGuard cannot tell which of two identical rows is 'the' row, so it warns).

    The table's primary key would forbid it, so the table is rebuilt without the key. Works on PostgreSQL and SQLite."""
    q = f"{schema}." if schema else ""
    with engine.begin() as c:
        c.execute(text(f"CREATE TABLE {q}rag_document_manifest_nokey AS SELECT * FROM {q}rag_document_manifest"))
        c.execute(text(f"DROP TABLE {q}rag_document_manifest"))
        c.execute(text(f"ALTER TABLE {q}rag_document_manifest_nokey RENAME TO rag_document_manifest"))
        c.execute(text(f"INSERT INTO {q}rag_document_manifest SELECT * FROM {q}rag_document_manifest "
                       "WHERE tenant_id = :t AND document_id = :d"), {"t": key[0], "d": key[1]})


# ---------------------------------------------------------------------------------------------- Lab B: mini bills
BILLS_BUCKET = "bills-lab"  # its own bucket: Lab A lists its whole bucket and would otherwise report these files as its own
BILLS_PREFIX = "bills/"
BILLS_COLLECTION = "bill_chunks"
BILLS_TABLE = "bill_documents"
NOW_STAMP = datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc)

# (bill, document, type, file in S3?, is_indexed, last_error, pieces in Qdrant for the bill, what was planted)
BILLS: tuple[tuple[str, str, str, bool, bool, str | None, int, str], ...] = (
    ("2300001", "2300001", "prefiled", True, True, None, 4, "Healthy: file, row marked indexed, 4 pieces in Qdrant."),
    ("2300002", "2300002", "prefiled", True, True, None, 6, "Healthy: 6 pieces."),
    ("2300003", "2300003", "prefiled", True, True, None, 3, "Healthy, but Qdrant stores this bill's ID as a whole number (numbers versus text)."),
    ("2300004", "2300004", "prefiled", True, True, None, 0, "The row says indexed, but Qdrant has nothing: a false success."),
    ("2300005", "2300005", "prefiled", True, False, "embedding timeout", 0, "Never indexed: the row says not indexed, Qdrant has nothing."),
    ("2200001", "3300001", "Introduced", True, True, None, 5, "One of two documents of bill 2200001; Qdrant only knows the bill."),
    ("2200001", "3300002", "Fiscal Note", True, True, None, 0, "The other document of bill 2200001 (its pieces cannot be told apart from the first)."),
    ("2200002", "3300003", "Introduced", True, True, None, 0, "A bill with nothing in Qdrant at all."),
)
BILLS_UNTRACKED = ("9000001", 2)  # a file with pieces in Qdrant but no manifest row
BILLS_ORPHAN = ("8000001", 3)  # pieces in Qdrant for a bill with no file and no row
BILLS_INT_ID = "2300003"  # this bill's id is written as a number in Qdrant


def _bill_key(bill: str, doc: str) -> str:
    return f"{BILLS_PREFIX}{bill}/{doc}.pdf"


def _bill_points(bill: str, count: int) -> list[Any]:
    from qdrant_client import models as qm

    out = []
    for i in range(count):
        snippet = f"Section {i + 1} of bill {bill}. " + make_text(f"{bill}:{i}", 1)[:160]
        payload = {
            "source_db": "lab", "source_table": "bills", "source_id": int(bill) if bill == BILLS_INT_ID else bill,
            "chunk_id": int(bill) * 100 + i, "jurisdiction": "NM", "text": snippet, "span": f"{i}:{i}", "modality": "text",
            "year": 2026, "bill_number": f"B{bill[-4:]}", "chamber": "S", "session_id": 2251,
        }
        out.append(qm.PointStruct(id=str(uuid.uuid5(uuid.NAMESPACE_URL, f"bills/{bill}/{i}")),
                                  vector=embed(snippet, 16, "demo-embed-v2"), payload=payload))
    return out


def seed_bills_lab(s3: Any, bucket: str, engine: Engine, qdrant: Any, *, schema: str | None = None) -> dict[str, int]:
    """Lab B: files under ``bills/`` in ``bucket``, a ``bill_documents`` table shaped like the real one, and a ``bill_chunks`` collection."""
    from qdrant_client import models as qm

    q = f"{schema}." if schema else ""
    pg = engine.dialect.name == "postgresql"
    flag, ts = ("boolean", "timestamptz") if pg else ("text", "text")  # SQLite has no boolean: the tests store 'True'/'False'
    stamp = NOW_STAMP.isoformat().replace("+00:00", "Z")

    # S3
    try:
        s3.head_bucket(Bucket=bucket)
    except Exception:
        s3.create_bucket(Bucket=bucket)
    files = 0
    for bill, doc, _typ, in_s3, *_rest in BILLS:
        if in_s3:
            s3.put_object(Bucket=bucket, Key=_bill_key(bill, doc), Body=f"%PDF-1.4 lab bill {bill} document {doc}".encode())
            files += 1
    s3.put_object(Bucket=bucket, Key=_bill_key(BILLS_UNTRACKED[0], BILLS_UNTRACKED[0]), Body=b"%PDF-1.4 lab untracked file")
    files += 1

    # the table
    with engine.begin() as c:
        c.execute(text(f"DROP TABLE IF EXISTS {q}{BILLS_TABLE}"))
        c.execute(text(f"""CREATE TABLE {q}{BILLS_TABLE} (
            id text PRIMARY KEY, bill_id text, external_bill_id text, external_doc_id text, document_type text, title text,
            s3_url text, source_url text, file_size_bytes bigint, page_count integer, is_indexed {flag}, indexed_at {ts},
            last_error text, created_at {ts}, updated_at {ts})"""))
        rows = []
        for bill, doc, typ, _in_s3, indexed, error, _pieces, _note in BILLS:
            rows.append({
                "id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"lab/{bill}/{doc}")), "bill_id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"lab/{bill}")),
                "eb": bill, "ed": doc, "dt": typ, "title": f"{typ} {doc}", "s3": f"https://{bucket}.s3.us-west-1.amazonaws.com/{_bill_key(bill, doc)}",
                "src": f"https://example.invalid/bills/{bill}", "size": 1000 + int(doc[-2:]), "pages": 3,
                "idx": bool(indexed) if pg else ("True" if indexed else "False"),
                "ia": stamp if indexed else None, "err": error, "ca": stamp, "ua": stamp,
            })
        c.execute(text(f"""INSERT INTO {q}{BILLS_TABLE}
            (id, bill_id, external_bill_id, external_doc_id, document_type, title, s3_url, source_url, file_size_bytes, page_count,
             is_indexed, indexed_at, last_error, created_at, updated_at)
            VALUES (:id, :bill_id, :eb, :ed, :dt, :title, :s3, :src, :size, :pages, :idx, :ia, :err, :ca, :ua)"""), rows)

    # Qdrant
    if BILLS_COLLECTION in {c.name for c in qdrant.get_collections().collections}:
        qdrant.delete_collection(BILLS_COLLECTION)
    qdrant.create_collection(BILLS_COLLECTION, vectors_config=qm.VectorParams(size=16, distance=qm.Distance.COSINE))
    points: list[Any] = []
    seen: set[str] = set()
    for bill, _doc, _typ, _in_s3, _idx, _err, pieces, _note in BILLS:
        if bill not in seen and pieces:
            points += _bill_points(bill, pieces)
        seen.add(bill)
    points += _bill_points(*BILLS_UNTRACKED) + _bill_points(*BILLS_ORPHAN)
    qdrant.upsert(BILLS_COLLECTION, points)
    return {"files": files, "rows": len(rows), "points": len(points)}


# ---------------------------------------------------------------------------------------------- one call for everything
def seed_everything(s3: Any, bucket: str, engine: Engine, qdrant: Any, *, schema: str | None = None,
                    bills_bucket: str = BILLS_BUCKET, say: Callable[[str], None] = print) -> LabWorld:
    from .seed import seed_manifest, seed_qdrant, seed_s3

    world = LabWorld()
    say(f"Lab A: {seed_s3(s3, bucket, world)} files in S3")
    say(f"Lab A: {seed_manifest(engine, world, schema=schema)} manifest rows")
    say(f"Lab A: {seed_qdrant(qdrant, world)} points in Qdrant ('{COLLECTION}')")
    seed_numeric_docs(s3, bucket, engine, qdrant, schema=schema)
    say(f"Lab A: {len(NUMERIC_DOCS)} numeric-ID practice documents added")
    dup = duplicate_row_target(world)
    seed_duplicate_manifest_row(engine, dup, schema=schema)
    say(f"Lab A: duplicate manifest row for {dup[0]}/{dup[1]}")
    b = seed_bills_lab(s3, bills_bucket, engine, qdrant, schema=schema)
    say(f"Lab B: {b['files']} files under '{BILLS_PREFIX}' in bucket '{bills_bucket}', {b['rows']} rows in '{BILLS_TABLE}', "
        f"{b['points']} points in '{BILLS_COLLECTION}'")
    return world


# ---------------------------------------------------------------------------------------------- the workbook
def _label(types: list[str]) -> str:
    return ", ".join(ISSUE_LABELS[IssueType(t)] for t in types)


def workbook_markdown() -> str:
    """lab/WORKBOOK.md: every planted fault with the answer RAGGuard should give, produced by running the real engine on the lab."""
    from ..engine.audit import AuditOptions, run_reconciliation
    from .world import DemoIndex, DemoManifest, DemoSource

    world = LabWorld(now=LAB_NOW)
    opts = AuditOptions(target=TARGET_FP, check_vectors=True, probe=True, now=LAB_NOW, grace_minutes=0)
    result = run_reconciliation(DemoSource(world), DemoManifest(world), DemoIndex(world), opts)
    found: dict[DocKey, list[str]] = {}
    for f in result.findings:
        found.setdefault(f.key, []).append(f"{ISSUE_LABELS[f.type]} ({f.severity.value})")

    lines = [
        "# Practice lab workbook", "",
        "Generated from `src/ragintegrity/demo/lab.py` by running the real audit on the lab, so it is always the right answer. "
        "A test fails if this file is out of date. Regenerate it with `python -m ragintegrity.demo.lab > lab/WORKBOOK.md`.", "",
        "## Lab A: the 30 documents", "",
        f"30 documents: {LAB_DOCS_PER_TENANT * len(world.tenants)} generated ones across three tenants ({', '.join(world.tenants)}) plus "
        f"{len(NUMERIC_DOCS)} ID-practice documents. Two of the generated documents are deleted from S3 on purpose (they are the leftovers), "
        f"so S3 itself holds {len(world.sources) + len(NUMERIC_DOCS)} files. {len(LAB_PLAN)} kinds of fault are planted, one document each. "
        "Run a full audit and compare with this table.", "",
        "| # | Document | What was planted | What RAGGuard should show | What users notice | The fix |",
        "|---|---|---|---|---|---|",
    ]
    n = 0
    seen: set[DocKey] = set()
    for name, _count in LAB_PLAN:
        for key, info in sorted(world.faults.items()):
            if info["fault"] != name or key in seen:
                continue
            seen.add(key)
            n += 1
            s = SCENARIOS[name]
            shows = "; ".join(found.get(key, ["(nothing)"]))
            lines.append(f"| {n} | `{key[0]}/{key[1]}` | **{s['title']}**: {s['planted']} | {shows} | {s['users']} | {s['fix']} |")
    extra = sorted(k for k in world.faults if k not in seen)
    for key in extra:  # the real document behind a tenant mismatch
        n += 1
        lines.append(f"| {n} | `{key[0]}/{key[1]}` | The real document of the tenant-mismatch fault above | "
                     f"{'; '.join(found.get(key, ['(nothing)']))} | It looks missing because its vectors carry another tenant's label. | "
                     "Fixed together with the tenant mismatch above. |")
    healthy = [k for k in sorted(world.sources) if k not in world.faults]
    lines += [
        "", f"The other **{len(healthy)} generated documents** are healthy: "
        + ", ".join(f"`{k[0]}/{k[1]}`" for k in healthy[:6]) + ", and so on.", "",
        "### What a full audit of the 27 generated documents should say", "",
        f"- {result.stats.get('documents_total')} entries compared (the wrongly labelled vectors count as one extra), "
        f"{result.stats.get('findings_total')} findings, health score {result.stats.get('health_score')}%.",
        "- Isolation page: overall **leak** (rows 13 and 14 are the tenant mismatch).",
        f"- **With the {len(NUMERIC_DOCS)} practice documents added (what you will see in the app):** {lab_a_totals(result.stats)['documents']} entries, "
        f"{result.stats.get('findings_total')} findings, health {lab_a_totals(result.stats)['health']}%, plus one duplicate-manifest-ID warning.", "",
        "### The ID practice documents (added to Lab A as well)", "",
        "| Document | What was planted | What RAGGuard should show |", "|---|---|---|",
    ]
    for tenant, doc, _typed, why in NUMERIC_DOCS:
        lines.append(f"| `{tenant}/{doc}` | {why[0].upper() + why[1:]}. | **Healthy.** The same ID written as a number, a decimal or text is one ID. "
                     "Setup check: shows how each system stores IDs. |")
    dup = duplicate_row_target(world)
    lines += [
        f"| `{dup[0]}/{dup[1]}` | Its manifest row exists twice (an exact copy). | The audit result carries a **duplicate manifest ID** warning "
        "(Overview and Audit History; the setup check too). The document itself stays healthy. |",
        "", "## Lab B: mini bills (practise the real sign-up and settings flow)", "",
        "A miniature of the real setup: files at `bills/<bill>/<document>.pdf` in the bucket `bills-lab`, a `bill_documents` table with a "
        "true/false `is_indexed`, and a `bill_chunks` collection whose pieces only know their bill (`source_id`). Open http://localhost:8001, "
        "**create an account** (any email and password, they stay on your computer) and type these into the pages, exactly as you would for "
        "a real customer. The addresses are the ones the app inside Docker uses to reach the other containers.", "",
        "| Page | Field | Value |", "|---|---|---|",
        "| Data Sources, Amazon S3 | Bucket / Key prefix / Region | `bills-lab` / `bills/` / `us-east-1` (**keep the slash at the end of the prefix**: "
        "without it the key pattern matches nothing, the audit sees 0 documents and shows \"0 issues\") |",
        "| | Custom endpoint | `http://s3:5000` |",
        "| | Access key ID / Secret access key | `test` / `test` (the lab's fake S3 accepts any keys) |",
        "| | Content hash | `etag` |",
        r"| | Key pattern (regex) | `^(?P<document_id>[^/]+)/(?P=document_id)\.pdf$` |",
        "| | Look up files from the manifest | on |",
        "| Data Sources, PostgreSQL | Connection string | `postgresql://postgres:postgres@postgres:5432/postgres` |",
        "| | Schema / Document table | `public` / `bill_documents` |",
        "| | Column map (JSON) | `{\"document_id\":\"external_doc_id\",\"source_uri\":\"s3_url\",\"processing_status\":\"is_indexed\"}` |",
        "| Data Sources, Qdrant | URL / Collections | `http://qdrant:6333` / `bill_chunks` |",
        "| | Payload field map (JSON) | `{\"document_id\":\"source_id\"}` |",
        "| Settings, Policy | Grace period (minutes) | `0` (the files were created seconds ago; with the default 10 two documents show as *pending*) |",
        "| | Required payload fields | `document_id` |",
        "| | Only audit documents found in the source (S3) | on |",
        "| Integrations, Repair webhook | Webhook URL / Signing secret | `http://worker-bills:9000/ragi-webhook` / `local-lab-secret` "
        "(only needed for the repair practice at the end) |", "",
        "Save each group, press **Check setup** on Data Sources, then **Run audit**. What each document should give:", "",
        "| Bill | Document | Type | Planted | With these settings |", "|---|---|---|---|---|",
    ]
    for bill, doc, typ, _s3, _indexed, _err, _p, note in BILLS:
        same = bill == doc
        verdict = ("outside the key pattern (folder differs from file name), not audited" if not same else
                   "**Critical: Missing embeddings**" if bill == "2300004" else "**High: Missing embeddings**" if bill == "2300005" else "Healthy")
        lines.append(f"| {bill} | {doc} | {typ} | {note} | {verdict} |")
    lines += [
        f"| {BILLS_UNTRACKED[0]} | {BILLS_UNTRACKED[0]} | (file only) | A file with {BILLS_UNTRACKED[1]} pieces in Qdrant but no table row. | "
        "Not seen while *Look up files from the manifest* is on (the blind spot). |",
        f"| {BILLS_ORPHAN[0]} | | (pieces only) | {BILLS_ORPHAN[1]} pieces in Qdrant for a bill with no file and no row. | "
        "Ignored while *Only audit documents found in the source* is on. |",
        "", "Expected audit with these settings: **5 documents compared, 2 findings** (one critical, one high), health 60%. "
        "The Isolation page says *limited* (the source-only switch hides wrong-tenant vectors).", "",
        "### Exercises: change one setting, run the audit, read the difference", "",
        "| # | Change | What you should see | What it teaches |", "|---|---|---|---|",
    ]
    lines += [f"| {i} | {change} | {see} | {teach} |" for i, (change, see, teach) in enumerate(BILLS_EXERCISES, 1)]
    lines += [
        "", "### Repair practice: fix the two broken bills", "",
        "Put the settings back as in the first table (and save the repair webhook from its last row), run the audit, then:", "",
        "1. **Integrity Issues**: tick both open issues (`2300004`, `2300005`) and press **Create repair plan**.",
        "2. Open the plan and press **Trigger repair**. RAGGuard sends a signed request to the Lab B worker (`worker-bills`).",
        "3. Press **Verify now**. The worker found each file from its address in the plan, wrote its pieces into `bill_chunks` and marked the "
        "row `is_indexed` in `bill_documents`, so both bills show **Completed**.",
        "4. **Run audit** again: **5 documents compared, 0 findings, health 100%**.", "",
        "Lab A has its own worker, so a repair there never touches Lab B (and the other way round). A worker is *your* pipeline: it must know "
        "where your files live and how your vectors and table are laid out, which is why the two labs need two workers.", "",
    ]
    return "\n".join(lines)


# Observed on real S3, Postgres and Qdrant, and asserted by tests/test_lab.py. (change, what you should see, what it teaches)
BILLS_EXERCISES: tuple[tuple[str, str, str], ...] = (
    ("Turn **off** *Look up files from the manifest*",
     "6 documents, 3 findings. The new one is `9000001`: **Metadata mismatch (medium)**, vectors but no table row.",
     "Without the lookup the app lists the bucket and finds files the table does not know (it also gets slow on a huge bucket)."),
    ("Turn **off** *Only audit documents found in the source*",
     "11 documents, 8 findings, health 27%: orphan vectors for bill `2200001`, orphan-row warnings for `3300001` to `3300003`, "
     "orphan vectors for `8000001` and `9000001`, plus the two real ones.",
     "Why the switch exists: the key pattern skips most documents, so everything the pattern skips looks like a leftover. "
     "On a big shared index the audit would also read every piece and run out of time."),
    ("Turn **off both** switches",
     "11 documents, 8 findings. Same as above, except `9000001` is now a **Metadata mismatch (medium)**.",
     "The two switches decide which of the two directions (file to shelf, shelf to file) the audit checks."),
    ("Per bill: Key pattern `^(?P<document_id>[^/]+)/[^/]+\\.pdf$` and Column map `document_id` set to `external_bill_id`",
     "7 documents, 3 findings (bill `2200002` **critical**, `2300004` critical, `2300005` high), a **duplicate manifest ID** warning, health 57%.",
     "Bill-level checking works, but bill `2200001` (two documents) would stay healthy even if only one of them were indexed, "
     "because Qdrant only knows the bill."),
)


def lab_a_totals(base_stats: dict[str, Any]) -> dict[str, Any]:
    """The totals Lab A shows once the 3 healthy practice documents are added to the 27 generated ones."""
    total = int(base_stats["documents_total"])
    healthy = round(float(base_stats["health_score"]) / 100 * total)
    return {"documents": total + len(NUMERIC_DOCS), "health": round(100 * (healthy + len(NUMERIC_DOCS)) / (total + len(NUMERIC_DOCS)), 1)}


if __name__ == "__main__":  # python -m ragintegrity.demo.lab > lab/WORKBOOK.md
    import sys

    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    print(workbook_markdown())
