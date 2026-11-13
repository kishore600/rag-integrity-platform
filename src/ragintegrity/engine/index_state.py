"""Streaming aggregation of the vector index into per-document state.

The index can hold millions of points, so we never keep point objects around. Each point is
classified the moment it is seen (against the live source inventory and the manifest) and folded
into a compact ``DocIndexState``.

Point classes
-------------
fresh     content hash/version matches the live source and the pipeline fingerprint matches the target
stale     content hash/version differs from the live source (an older version of the document)
outdated  content is current but it was built with a different parser/chunker/embedding config
unknown   the payload carries no hash/version, so freshness cannot be established from the index
orphan    the document does not exist in the source any more
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field

from ..ids import normalize_hash, same_hash
from ..models import ChunkRow, DocKey, Fingerprint, IndexedChunk, ManifestRow, SourceDoc

FRESH, STALE, OUTDATED, UNKNOWN, ORPHAN = "fresh", "stale", "outdated", "unknown", "orphan"
LIVE_CLASSES = (FRESH, UNKNOWN)


class ChunkSlot:
    __slots__ = ("index", "ids", "hash")

    def __init__(self, index: int | None, chunk_hash: str | None = None) -> None:
        self.index = index
        self.ids: list[str] = []
        self.hash = chunk_hash  # the chunk hash the first point of this chunk carried (None when the payload has none)


@dataclass
class DocIndexState:
    tenant_id: str
    document_id: str
    collections: set[str] = field(default_factory=set)
    point_count: int = 0
    classes: Counter = field(default_factory=Counter)
    # (collection, chunk_key, class) -> slot holding every point id for that chunk
    slots: dict[tuple[str, str, str], ChunkSlot] = field(default_factory=dict)
    hashes: Counter = field(default_factory=Counter)
    versions: Counter = field(default_factory=Counter)
    fp_live: Counter = field(default_factory=Counter)
    fp_all: Counter = field(default_factory=Counter)
    fp_objs: dict[str, Fingerprint] = field(default_factory=dict)
    acl: Counter = field(default_factory=Counter)
    missing_fields: Counter = field(default_factory=Counter)
    empty_vector_ids: list[tuple[str, str]] = field(default_factory=list)  # (collection, point_id)
    outdated_conflicts: dict[str, dict] = field(default_factory=dict)
    sample_ids: list[str] = field(default_factory=list)
    # chunk hashes against the chunk manifest: points compared, points whose hash differs, of those how many were therefore
    # counted as stale (the payload said nothing else about the revision), and a few examples
    chunk_hash_checked: int = 0
    chunk_hash_bad: int = 0
    chunk_hash_reclassified: int = 0
    chunk_hash_examples: list[dict] = field(default_factory=list)

    @property
    def key(self) -> DocKey:
        return (self.tenant_id, self.document_id)

    def live_count(self) -> int:
        return self.classes[FRESH] + self.classes[UNKNOWN]

    def points_of(self, *classes: str) -> dict[str, list[str]]:
        """Point ids by collection for the given classes."""
        out: dict[str, list[str]] = {}
        for (coll, _ck, cls), slot in self.slots.items():
            if cls in classes:
                out.setdefault(coll, []).extend(slot.ids)
        return out

    def duplicate_points(self) -> tuple[dict[str, list[str]], int, list[str]]:
        """Extra copies among *live* points: ({collection: [ids to drop]}, duplicated chunk count, examples)."""
        drop: dict[str, list[str]] = {}
        dup_chunks = 0
        examples: list[str] = []
        for (coll, ck, cls), slot in self.slots.items():
            if cls in LIVE_CLASSES and len(slot.ids) > 1:
                dup_chunks += 1
                drop.setdefault(coll, []).extend(slot.ids[1:])  # keep the first-seen copy
                if len(examples) < 10:
                    examples.append(ck)
        return drop, dup_chunks, examples

    def live_chunks(self) -> dict[str, dict[str, int | None]]:
        """{collection: {chunk_key: chunk_index}} for live (fresh/unknown) points."""
        out: dict[str, dict[str, int | None]] = {}
        for (coll, ck, cls), slot in self.slots.items():
            if cls in LIVE_CLASSES:
                out.setdefault(coll, {})[ck] = slot.index
        return out


@dataclass
class AggContext:
    source: dict[DocKey, SourceDoc]
    manifest: dict[DocKey, ManifestRow]
    target: Fingerprint | None = None
    default_tenant: str = "default"
    required_fields: list[str] = field(default_factory=list)
    chunk_rows: dict[DocKey, dict[str, ChunkRow]] | None = None  # the chunk manifest: what the pipeline recorded for each chunk


class IndexAggregator:
    def __init__(self, ctx: AggContext) -> None:
        self.ctx = ctx
        self.states: dict[DocKey, DocIndexState] = {}
        self.unattributed: dict[str, list] = {}  # collection -> [count, sample ids]
        self.points_seen = 0
        # tenant isolation coverage, counted for every point seen (even one without a document id)
        self.iso_points: Counter = Counter()
        self.iso_no_tenant: Counter = Counter()  # the payload carried no tenant label (so it is assumed to be the default tenant)
        self.iso_no_acl: Counter = Counter()  # the payload carried no permission (ACL) hash

    # ------------------------------------------------------------------------------------
    def add_all(self, chunks: Iterable[IndexedChunk]) -> IndexAggregator:
        for c in chunks:
            self.add(c)
        return self

    def add(self, c: IndexedChunk) -> None:
        self.points_seen += 1
        iso_tenant = c.tenant_id or self.ctx.default_tenant
        self.iso_points[iso_tenant] += 1
        if not c.tenant_id:
            self.iso_no_tenant[iso_tenant] += 1
        if not c.acl_hash:
            self.iso_no_acl[iso_tenant] += 1
        if not c.document_id:
            slot = self.unattributed.setdefault(c.collection, [0, []])
            slot[0] += 1
            if len(slot[1]) < 10:
                slot[1].append(c.point_id)
            return

        tenant = c.tenant_id or self.ctx.default_tenant
        key = (tenant, c.document_id)
        st = self.states.get(key)
        if st is None:
            st = self.states[key] = DocIndexState(tenant_id=tenant, document_id=c.document_id)
        src = self.ctx.source.get(key)
        man = self.ctx.manifest.get(key)

        fp = c.fingerprint.fill_from(man.fingerprint if man else None)
        cls = self._classify(c, src, fp, st)
        cls = self._check_chunk_hash(c, key, cls, st)

        st.point_count += 1
        st.collections.add(c.collection)
        st.classes[cls] += 1
        if len(st.sample_ids) < 5:
            st.sample_ids.append(c.point_id)
        st.hashes[normalize_hash(c.source_hash)] += 1
        if c.source_version:
            st.versions[c.source_version] += 1
        if c.acl_hash:
            st.acl[c.acl_hash] += 1

        chunk_key = c.chunk_id or (f"idx:{c.chunk_index}" if c.chunk_index is not None else f"pt:{c.point_id}")
        slot_key = (c.collection, chunk_key, cls)
        slot = st.slots.get(slot_key)
        if slot is None:
            slot = st.slots[slot_key] = ChunkSlot(c.chunk_index, c.chunk_hash)
        slot.ids.append(c.point_id)

        fk = fp.key()
        st.fp_objs.setdefault(fk, fp)
        st.fp_all[fk] += 1
        if cls in LIVE_CLASSES:
            st.fp_live[fk] += 1

        for f in self.ctx.required_fields:
            if f not in c.present_fields:
                st.missing_fields[f] += 1
        if c.vector_checked and not c.vector_ok:
            st.empty_vector_ids.append((c.collection, c.point_id))

    def _check_chunk_hash(self, c: IndexedChunk, key: DocKey, cls: str, st: DocIndexState) -> str:
        """Compare this point's chunk hash with the one the pipeline recorded for the same chunk id.

        A chunk id alone does not say which revision of the text it holds. When the payload carries no hash or version
        for the document itself (class ``unknown``), a chunk whose hash differs from the manifest's is the only evidence
        of the revision there is, so it counts as stale. When the document hash already says the point is current, a
        different chunk hash is not reclassified (the two sides may compute chunk hashes differently, or the chunking
        changed); it is counted and reported as a metadata problem."""
        rows = self.ctx.chunk_rows
        if not rows or not c.chunk_id or not c.chunk_hash or cls not in LIVE_CLASSES:
            return cls  # a point already known to be an older revision (or to belong to no document) has nothing more to say
        expected = rows.get(key, {}).get(c.chunk_id)
        if expected is None or not expected.chunk_hash:
            return cls
        st.chunk_hash_checked += 1
        if same_hash(expected.chunk_hash, c.chunk_hash):
            return cls
        st.chunk_hash_bad += 1
        if len(st.chunk_hash_examples) < 5:
            st.chunk_hash_examples.append({"chunk_id": c.chunk_id, "expected": expected.chunk_hash, "indexed": c.chunk_hash})
        if cls == UNKNOWN:
            st.chunk_hash_reclassified += 1
            return STALE
        return cls

    def _classify(self, c: IndexedChunk, src: SourceDoc | None, fp: Fingerprint, st: DocIndexState) -> str:
        if src is None:
            return ORPHAN
        fresh: bool | None = None
        if c.source_hash and src.source_hash:
            fresh = same_hash(c.source_hash, src.source_hash)
        elif c.source_version and src.source_version:
            fresh = c.source_version == src.source_version
        if fresh is False:
            return STALE
        if self.ctx.target is not None:
            conflicts = fp.conflicts_with(self.ctx.target)
            if conflicts:
                for k, v in conflicts.items():
                    st.outdated_conflicts.setdefault(k, v)
                return OUTDATED
        return FRESH if fresh else UNKNOWN
