import { documentName } from "@/lib/format";
import type { AuditRun } from "@/types/api";

/** "repair-verify" or "severity_changed" as readable words. */
export const humanize = (s: string): string => {
  const t = s.replace(/[_-]+/g, " ").trim();
  return t.charAt(0).toUpperCase() + t.slice(1);
};

export const kindLabel = (kind: string): string => humanize(kind);

/** What an audit looked at: one tenant, a list of documents, or everything. */
export function scopeLabel(run: Pick<AuditRun, "scope">): string {
  const { tenant, documents } = run.scope ?? {};
  if (tenant) return tenant;
  if (documents) return `${documents} ${documents === 1 ? "document" : "documents"}`;
  return "All";
}

/** The file name of a document, or a plain label for an issue that belongs to the whole tenant. */
export const documentLabel = (documentId: string): string => (documentId === "*" ? "Whole tenant" : documentName(documentId));
