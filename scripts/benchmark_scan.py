"""How fast can a collection be read? Measures the Qdrant calls an audit makes, so performance is promised from numbers.

Two modes, both safe:

    python scripts/benchmark_scan.py --synthetic 150000
        Builds a throw-away collection of N points on a LOCAL Qdrant (localhost / 127.0.0.1 only: it refuses any other host
        because it writes), measures, and deletes it. Needs RAGI_QDRANT_URL (and RAGI_QDRANT_API_KEY if the server enforces one).

    python scripts/benchmark_scan.py --collection bill_chunks --limit 200000 --id-field source_id
        READ-ONLY on any cluster (including a customer's): reads at most --limit points of an existing collection and measures
        the full scroll and a filtered scroll by document id. Nothing is written.

What it measures: points per second of a plain scroll (payload only) at several page sizes; the cost of one slice, that is a
scroll filtered by N document ids (what a sliced audit does per slice); and the slice size at which a filtered pass stops
being cheaper than reading everything. Without a payload index on the id field a filtered scroll scans the collection, so
its time depends on the collection size, not on the number of ids: that is why a slice is thousands of documents.
"""

from __future__ import annotations

import argparse
import os
import random
import sys
import time
import uuid
from urllib.parse import urlparse

from qdrant_client import QdrantClient
from qdrant_client import models as qm

LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


def timed(fn):
    t0 = time.perf_counter()
    out = fn()
    return out, time.perf_counter() - t0


def scroll_all(client, name, page, limit, payload, flt=None):
    read, offset = 0, None
    while read < limit:
        points, offset = client.scroll(name, scroll_filter=flt, limit=min(page, limit - read), offset=offset, with_payload=payload,
                                       with_vectors=False)
        read += len(points)
        if offset is None or not points:
            break
    return read


def report(label, points, seconds):
    rate = points / seconds if seconds else float("inf")
    print(f"  {label:<46}{points:>10,} points  {seconds:>7.2f} s  {rate:>10,.0f} points/s")
    return rate


def run(client, name, id_field, limit, chunks_per_doc):
    total = client.count(name, exact=False).count
    limit = min(limit, total)
    print(f"\ncollection {name!r}: about {total:,} points; measuring up to {limit:,}\n")
    print("plain scroll (payload only), by page size")
    for page in (100, 256, 1000):
        n, s = timed(lambda page=page: scroll_all(client, name, page, limit, [id_field]))
        report(f"page size {page}", n, s)

    sample, _ = client.scroll(name, limit=min(5000, limit), with_payload=[id_field], with_vectors=False)
    ids = sorted({str(p.payload.get(id_field)) for p in sample if p.payload and p.payload.get(id_field) is not None})
    if not ids:
        print(f"\n(no payload field {id_field!r} found: skipping the filtered measurements)")
        return
    print(f"\nfiltered scroll by document id on {id_field!r} (the cost of one slice of a sliced audit; page size 1000)")
    for n_ids in (10, 100, 1000, 5000):
        pick = random.sample(ids, min(n_ids, len(ids)))
        numbers = [int(i) for i in pick if i.isdigit()]
        should = [qm.FieldCondition(key=id_field, match=qm.MatchAny(any=pick))]
        if numbers:
            should.append(qm.FieldCondition(key=id_field, match=qm.MatchAny(any=numbers)))
        flt = qm.Filter(should=should)
        try:
            n, s = timed(lambda flt=flt: scroll_all(client, name, 1000, total, [id_field], flt))
        except Exception as exc:
            print(f"  {n_ids:>5} ids: refused ({type(exc).__name__}: {str(exc)[:90]})")
            continue
        report(f"{len(pick):,} document ids", n, s)
    print("\nreading: a filtered pass over a collection WITHOUT a payload index on the id field costs about one full scan per slice,")
    print("whatever the number of ids, so use big slices (audit_slice_documents, default 5000). With a keyword index it is far cheaper.")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", default=os.environ.get("RAGI_QDRANT_URL", "http://127.0.0.1:6333"))
    ap.add_argument("--api-key", default=os.environ.get("RAGI_QDRANT_API_KEY"))
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--synthetic", type=int, metavar="N", help="build a throw-away collection of N points (local Qdrant only)")
    g.add_argument("--collection", help="measure an existing collection (read-only)")
    ap.add_argument("--limit", type=int, default=200_000, help="most points to read per measurement (read-only mode)")
    ap.add_argument("--id-field", default="document_id", help="the payload field that holds the document id")
    ap.add_argument("--chunks-per-doc", type=int, default=10, help="chunks per document in the synthetic collection")
    args = ap.parse_args()

    client = QdrantClient(url=args.url, api_key=args.api_key, timeout=120, check_compatibility=False)
    if args.collection:
        run(client, args.collection, args.id_field, args.limit, args.chunks_per_doc)
        return 0

    host = urlparse(args.url).hostname or ""
    if host not in LOCAL_HOSTS:
        print(f"refusing: --synthetic writes, so it only runs against a local Qdrant (got host {host!r}).", file=sys.stderr)
        return 2
    name = f"ragi_bench_{uuid.uuid4().hex[:8]}"
    docs = max(1, args.synthetic // args.chunks_per_doc)
    print(f"building {name}: {args.synthetic:,} points, {docs:,} documents ...")
    client.create_collection(name, vectors_config=qm.VectorParams(size=4, distance=qm.Distance.COSINE))
    try:
        t0 = time.perf_counter()
        batch = []
        for i in range(args.synthetic):
            d = i // args.chunks_per_doc
            batch.append(qm.PointStruct(id=i + 1, vector=[random.random() for _ in range(4)], payload={
                "document_id": str(100000 + d), "chunk_id": f"{100000 + d}#{i % args.chunks_per_doc}", "chunk_index": i % args.chunks_per_doc,
                "source_hash": "h" * 64}))
            if len(batch) == 2000:
                client.upsert(name, points=batch, wait=False)
                batch = []
        if batch:
            client.upsert(name, points=batch, wait=True)
        while client.count(name, exact=True).count < args.synthetic:
            time.sleep(0.5)
        print(f"  built in {time.perf_counter() - t0:.1f} s")
        run(client, name, "document_id", args.synthetic, args.chunks_per_doc)
    finally:
        client.delete_collection(name)
        print(f"\ndeleted {name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
