/** Plain-language names for the things the backend records (events, actions, checks) and helpers for reading evidence. */
import type { Tone } from "@/components/ui/badge";
import { formatNumber, shortHash } from "@/lib/format";
import type { IssueEvent, RepairAction, RepairEvent, RepairItem, Severity } from "@/types/api";

export const cap = (s: string): string => s.charAt(0).toUpperCase() + s.slice(1).replace(/_/g, " ");

const num = (v: unknown): number | undefined => (typeof v === "number" ? v : undefined);
const str = (v: unknown): string | undefined => (typeof v === "string" ? v : undefined);

// ---- issue timeline ---------------------------------------------------------------------------------------
export function describeIssueEvent(e: IssueEvent): { title: string; tone: Tone; body?: string } {
  const d = e.details ?? {};
  switch (e.event) {
    case "opened":
      return { title: "Detected by an audit", tone: "warning", body: str(d.severity) ? `Severity: ${cap(str(d.severity)!)}` : undefined };
    case "reopened":
      return { title: "Came back after it was resolved", tone: "critical", body: str(d.severity) ? `Severity: ${cap(str(d.severity)!)}` : undefined };
    case "resolved":
      return { title: "Resolved: the index now matches the source", tone: "success" };
    case "severity_changed":
      return { title: `Severity changed from ${cap(str(d.from) ?? "unknown")} to ${cap(str(d.to) ?? "unknown")}`, tone: "info" };
    case "ignored":
      return { title: "Ignored", tone: "neutral", body: str(d.reason) ? `Reason: ${str(d.reason)}` : undefined };
    case "unignored":
      return { title: "Reopened by a user", tone: "warning" };
    default:
      return { title: cap(e.event), tone: "neutral" };
  }
}

// ---- repair plans -------------------------------------------------------------------------------------------
export const ACTION_LABEL: Record<RepairAction, string> = {
  reindex_full: "Full reindex",
  reindex_chunks: "Re-embed missing chunks",
  cleanup_vectors: "Remove old vectors",
  fix_metadata: "Fix metadata",
  investigate: "Needs a human",
};

export function describeRepairEvent(e: RepairEvent): { title: string; tone: Tone; body?: string } {
  const d = e.details ?? {};
  const plural = (n: number | undefined, one: string, many: string) => (n === undefined ? undefined : `${formatNumber(n)} ${n === 1 ? one : many}`);
  switch (e.event) {
    case "created":
      return { title: "Plan created", tone: "neutral", body: [plural(num(d.documents), "document", "documents"), plural(num(d.issues), "issue", "issues")].filter(Boolean).join(", ") || undefined };
    case "reindex_triggered":
      return { title: "Repair sent to your worker", tone: "info", body: plural(num(d.documents), "document to reprocess", "documents to reprocess") };
    case "verified": {
      const result = str(d.result);
      const done = num(d.completed);
      const total = num(d.total);
      const failedDocs = Array.isArray(d.failed_documents) ? d.failed_documents.filter((x): x is string => typeof x === "string") : [];
      const counts = done !== undefined && total !== undefined ? `${formatNumber(done)} of ${formatNumber(total)} documents complete` : undefined;
      const failed = failedDocs.length ? `Still failing: ${failedDocs.slice(0, 3).join(", ")}${failedDocs.length > 3 ? ` and ${failedDocs.length - 3} more` : ""}` : undefined;
      const body = [counts, failed].filter(Boolean).join(". ") || undefined;
      if (result === "completed") return { title: "Verified: every repair is in place", tone: "success", body };
      if (result === "cleanup_pending") return { title: "Verified: replacements are in place, old vectors await approval", tone: "warning", body };
      if (result === "partial") return { title: "Verified: some documents still have issues", tone: "warning", body };
      return { title: "Verified: the repairs are not in place yet", tone: "critical", body };
    }
    case "cleanup_triggered":
      return {
        title: "Cleanup sent to your worker",
        tone: "info",
        body: [plural(num(d.points), "vector", "vectors"), plural(num(d.documents), "document", "documents")].filter(Boolean).join(" in ") || undefined,
      };
    case "worker_callback":
      return { title: "Your worker reported back", tone: "neutral" };
    default:
      return { title: cap(e.event), tone: "neutral" };
  }
}

export const ITEM_STATUS: Record<string, { label: string; tone: Tone }> = {
  planned: { label: "Planned", tone: "neutral" },
  reindexed: { label: "Replacements verified", tone: "warning" },
  awaiting_cleanup: { label: "Waiting for cleanup", tone: "warning" },
  completed: { label: "Completed", tone: "success" },
  failed: { label: "Not fixed yet", tone: "critical" },
};
export const itemStatus = (s: string): { label: string; tone: Tone } => ITEM_STATUS[s] ?? { label: cap(s), tone: "neutral" };

export const CHECK_LABEL: Record<string, string> = {
  expected_chunks_present: "All chunks present",
  embeddings_present: "Embeddings present",
  latest_version_indexed: "Latest version indexed",
  metadata_correct: "Metadata correct",
  old_vectors_inactive: "Old vectors removed",
};
export const checkLabel = (k: string): string => CHECK_LABEL[k] ?? cap(k);

/** What a repair item will do, in words: chunks to regenerate and vectors to remove. */
export function itemWork(it: Pick<RepairItem, "actions" | "cleanup" | "cleanup_vectors" | "expected_chunk_count" | "missing_count">): string[] {
  const lines: string[] = [];
  if (it.actions.includes("reindex_full")) {
    lines.push(it.expected_chunk_count ? `${formatNumber(it.expected_chunk_count)} chunks to regenerate` : "Whole document to regenerate");
  } else if (it.actions.includes("reindex_chunks")) {
    lines.push(`${formatNumber(Math.max(1, it.missing_count))} chunk${it.missing_count === 1 ? "" : "s"} to regenerate`);
  }
  if (it.cleanup) lines.push(it.cleanup_vectors > 0 ? `${formatNumber(it.cleanup_vectors)} vectors to remove` : "Old vectors to remove");
  return lines;
}

// ---- evidence ----------------------------------------------------------------------------------------------
const HANDLED_EVIDENCE_KEYS = new Set(["retrieval_probe", "problems", "removal_points", "removal_count", "missing_chunks"]);

export interface EvidenceFact {
  label: string;
  /** A plain value, or a list rendered as chips. */
  value?: string;
  list?: string[];
  full?: string;
}

/** The simple facts in the evidence (numbers, short text, short lists) that the structured views above do not already show. */
export function evidenceFacts(evidence: Record<string, unknown>): EvidenceFact[] {
  const out: EvidenceFact[] = [];
  for (const [k, v] of Object.entries(evidence)) {
    if (HANDLED_EVIDENCE_KEYS.has(k) || v === null || v === undefined) continue;
    const label = cap(k);
    if (typeof v === "number") out.push({ label, value: formatNumber(v) });
    else if (typeof v === "boolean") out.push({ label, value: v ? "Yes" : "No" });
    else if (typeof v === "string") {
      if (!v) continue;
      out.push(v.length > 48 ? { label, value: shortHash(v, 16), full: v } : { label, value: v });
    } else if (Array.isArray(v) && v.length > 0 && v.length <= 8 && v.every((x) => typeof x === "string" && x.length <= 80)) {
      out.push({ label, list: v as string[] });
    }
  }
  return out.slice(0, 14);
}

export const isSeverity = (s: string): s is Severity => ["critical", "high", "medium", "low", "info"].includes(s);
