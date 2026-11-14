/**
 * What each integrity issue type means. This is the product's knowledge of its own findings: the label, why it matters,
 * how the expected and actual state are described from the evidence the backend stores, which systems are involved, and the
 * safe remediation. It never invents data: every number comes from the issue's evidence.
 */
import type { Issue, IssueType, RepairAction, Severity, DocumentRow } from "@/types/api";
import { shortHash } from "./format";

export type DataSource = "Amazon S3" | "Manifest" | "Vector index";

interface Meta {
  label: string;
  why: string;
  sources: DataSource[];
}

export const ISSUE_META: Record<IssueType, Meta> = {
  missing_embedding: {
    label: "Missing embeddings",
    why: "The document exists at the source but nothing about it is searchable, so users get no answer from it. When the pipeline reported success, job status alone would never have caught this.",
    sources: ["Amazon S3", "Vector index"],
  },
  partial_index: {
    label: "Partial index",
    why: "Only part of the document is searchable. Answers can be silently incomplete, and the missing chunks are exactly the ones nobody notices are gone.",
    sources: ["Vector index", "Manifest"],
  },
  stale_embedding: {
    label: "Stale document version",
    why: "The source changed but the index still describes the previous version, so users are served outdated content with full confidence.",
    sources: ["Amazon S3", "Vector index"],
  },
  superseded_active: {
    label: "Superseded vectors active",
    why: "The latest version is indexed, but older-generation vectors still answer queries and can outrank the current content.",
    sources: ["Vector index"],
  },
  orphan_vector: {
    label: "Orphan vectors",
    why: "The document was deleted at the source but its vectors remain searchable, so deleted or withdrawn content can still be returned to users.",
    sources: ["Amazon S3", "Vector index"],
  },
  duplicate_chunk: {
    label: "Duplicate chunks",
    why: "The same chunk is indexed more than once (typically a retried job), which skews ranking and wastes storage and tokens.",
    sources: ["Vector index"],
  },
  metadata_inconsistent: {
    label: "Metadata mismatch",
    why: "The source, the manifest and the vector payloads disagree (counts, versions, ACL hash, missing fields). Permission filters and freshness checks depend on this metadata being right.",
    sources: ["Manifest", "Vector index"],
  },
  pipeline_drift: {
    label: "Pipeline drift",
    why: "Vectors were built with a different parser, chunker or embedding model than the target. Mixed embedding spaces degrade retrieval quality in ways that are hard to see.",
    sources: ["Manifest", "Vector index"],
  },
  empty_embedding: {
    label: "Empty embeddings",
    why: "Points exist with a missing or all-zero vector, so they can never be retrieved correctly.",
    sources: ["Vector index"],
  },
  tenant_mismatch: {
    label: "Tenant mismatch",
    why: "Vectors are tagged with the wrong tenant, which can leak one customer's content to another. Treat as a security incident.",
    sources: ["Vector index"],
  },
  manifest_orphan: {
    label: "Orphan manifest row",
    why: "The manifest still lists a document that no longer exists at the source or in the index. Harmless to users, but it clutters your records.",
    sources: ["Manifest"],
  },
};

export const ISSUE_TYPES = Object.keys(ISSUE_META) as IssueType[];
export const issueLabel = (t: string): string => ISSUE_META[t as IssueType]?.label ?? t.replace(/_/g, " ");
export const issueSources = (t: string): DataSource[] => ISSUE_META[t as IssueType]?.sources ?? [];
export const DATA_SOURCES: DataSource[] = ["Amazon S3", "Manifest", "Vector index"];

export const SEVERITIES: Severity[] = ["critical", "high", "medium", "low"];
export const severityRank: Record<Severity, number> = { critical: 4, high: 3, medium: 2, low: 1, info: 0 };

export const REMEDIATION: Record<RepairAction, string> = {
  reindex_full: "Re-process the whole document from the latest source: parse, chunk, embed and upsert, then update the manifest.",
  reindex_chunks: "Re-embed only the missing chunks. A full rebuild of the document is also safe.",
  cleanup_vectors: "Remove the listed vectors, but only after their replacements are verified and an operator approves the removal.",
  fix_metadata: "Correct the manifest or payload metadata. No re-embedding is needed.",
  investigate: "Needs a human to look at it; there is no automatic repair.",
};

const num = (v: unknown): number | undefined => (typeof v === "number" ? v : undefined);
const str = (v: unknown): string | undefined => (typeof v === "string" ? v : undefined);
const strs = (v: unknown): string[] => (Array.isArray(v) ? v.filter((x): x is string => typeof x === "string") : []);

/** The expected and the actual state, in words, read from the stored evidence. */
export function describeStates(issue: Pick<Issue, "type" | "evidence">): { expected: string; actual: string } {
  const e = issue.evidence;
  switch (issue.type) {
    case "missing_embedding": {
      const n = num(e.expected_chunk_count);
      return {
        expected: n ? `${n} chunks indexed for the current version` : "The current version fully indexed",
        actual: `0 vectors in the index${e.pipeline_reported_success ? " (the pipeline reported success)" : ""}`,
      };
    }
    case "partial_index":
      return {
        expected: `${num(e.expected_chunks) ?? "All"} chunks indexed`,
        actual: `${num(e.indexed_chunks) ?? 0} indexed, ${num(e.missing_count) ?? "some"} missing`,
      };
    case "stale_embedding": {
      const idx = strs(e.indexed_hashes);
      return {
        expected: `Index built from source ${shortHash(str(e.source_hash))}`,
        actual: idx.length ? `Index built from ${shortHash(idx[0])}` : "Index built from an older version",
      };
    }
    case "superseded_active": {
      const stale = (num(e.stale_points) ?? 0) + (num(e.outdated_config_points) ?? 0);
      return { expected: "Only current-generation vectors are active", actual: `${num(e.live_points) ?? 0} current and ${stale} superseded vectors active` };
    }
    case "orphan_vector":
      return { expected: "No vectors: the document no longer exists at the source", actual: `${num(e.point_count) ?? 0} vectors still searchable` };
    case "duplicate_chunk":
      return {
        expected: "One vector per chunk",
        actual: `${num(e.duplicated_chunks) ?? 0} chunks indexed more than once (${num(e.extra_points) ?? 0} extra vectors)`,
      };
    case "metadata_inconsistent": {
      const first = e.problems?.[0]?.message;
      const n = e.problems?.length ?? 0;
      return { expected: "Source, manifest and payloads agree", actual: first ? `${first}${n > 1 ? ` (+${n - 1} more)` : ""}` : "Metadata disagrees between systems" };
    }
    case "pipeline_drift": {
      const diff = (e.differences ?? {}) as Record<string, { indexed: unknown; target: unknown }>;
      const parts = Object.entries(diff).map(([k, v]) => `${k.replace(/_/g, " ")}: ${String(v.indexed)} → ${String(v.target)}`);
      const varying = strs(e.varying_fields);
      return {
        expected: "Vectors built with the target pipeline",
        actual: parts.length ? parts.join("; ") : varying.length ? `Mixed configurations (${varying.join(", ")})` : "Built with a different configuration",
      };
    }
    case "empty_embedding":
      return { expected: "A usable vector for every point", actual: `${num(e.empty_points) ?? 0} points with empty or all-zero vectors` };
    case "tenant_mismatch": {
      const expected = strs(e.expected_tenants);
      return {
        expected: expected.length ? `Vectors tagged with tenant ${expected.join(", ")}` : "Vectors tagged with their owner",
        actual: `${num(e.point_count) ?? 0} vectors tagged with another tenant`,
      };
    }
    case "manifest_orphan":
      return { expected: "No manifest row for a deleted document", actual: `Row present (status ${str(e.manifest_status) ?? "unknown"})` };
  }
}

// ---- documents --------------------------------------------------------------------------------------------
export type DocState = "healthy" | "stale" | "missing" | "processing" | "failed";
export const DOC_STATE_LABEL: Record<DocState, string> = {
  healthy: "Healthy",
  stale: "Stale",
  missing: "Missing embeddings",
  processing: "Processing",
  failed: "Failed",
};

/** The embedding status shown in the Documents table, derived from the audit's document status and issue types. */
export function documentState(doc: Pick<DocumentRow, "status" | "issue_types">): DocState {
  if (doc.status === "pending") return "processing";
  if (doc.issue_types.includes("missing_embedding")) return "missing";
  if (doc.issue_types.includes("stale_embedding")) return "stale";
  if (doc.status === "healthy") return "healthy";
  if (doc.status === "broken" || doc.status === "orphaned") return "failed";
  return "stale"; // degraded: indexed, but something about it needs attention
}
