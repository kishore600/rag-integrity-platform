import type { ColumnDef } from "@tanstack/react-table";
import { ArrowRight, Info, ShieldCheck } from "lucide-react";
import { Link, useNavigate } from "react-router-dom";
import { Card, CardHeader } from "@/components/ui/card";
import { LinkButton } from "@/components/shared/link-button";
import { DataTable } from "@/components/shared/data-table";
import { EmptyState } from "@/components/shared/states";
import { IssueStatusBadge, SeverityBadge } from "@/components/shared/status";
import { documentName, formatNumber } from "@/lib/format";
import { issueLabel, severityRank } from "@/lib/issue-meta";
import { links } from "@/lib/links";
import type { IsolationFinding } from "@/types/api";
import { RunFullAuditButton } from "./run-audit-button";

const stop = (e: { stopPropagation: () => void }) => e.stopPropagation();

const columns: ColumnDef<IsolationFinding>[] = [
  {
    id: "severity",
    header: "Severity",
    accessorFn: (f) => severityRank[f.severity],
    meta: { className: "w-[120px]" },
    cell: ({ row }) => <SeverityBadge severity={row.original.severity} />,
  },
  {
    id: "issue",
    header: "Issue",
    accessorFn: (f) => f.title,
    meta: { className: "min-w-[240px]" },
    cell: ({ row }) => (
      <div className="min-w-0 max-w-[420px]">
        {/* a real link (open in a new tab, copy the address); the whole row also opens it */}
        <Link to={links.issue(row.original.issue_id)} onClick={stop} onKeyDown={stop} className="block truncate font-medium text-ink hover:text-brand" title={row.original.title}>
          {row.original.title}
        </Link>
        <p className="truncate text-support text-ink-2">{issueLabel(row.original.type)}</p>
      </div>
    ),
  },
  {
    id: "tenant",
    header: () => <span title="The tenant the document's vectors are indexed under">Tenant</span>,
    accessorFn: (f) => f.tenant_id,
    cell: ({ row }) => (
      <span className="block max-w-[180px] truncate text-ink-2" title={row.original.tenant_id}>
        {row.original.tenant_id}
      </span>
    ),
  },
  {
    id: "document",
    header: "Document",
    accessorFn: (f) => documentName(f.document_id),
    cell: ({ row }) => {
      const id = row.original.document_id;
      return (
        <span className="block max-w-[240px] truncate text-ink" title={id}>
          {id === "*" ? "Whole tenant" : documentName(id)}
        </span>
      );
    },
  },
  { id: "status", header: "Status", accessorFn: (f) => f.status, meta: { className: "w-[110px]" }, cell: ({ row }) => <IssueStatusBadge status={row.original.status} /> },
];

/**
 * The issues that are open right now: documents under the wrong tenant, and permission labels that disagree with the manifest.
 * The summary above describes the last full audit; this list is live, so it says when the two no longer agree.
 */
export function FindingsCard({ findings, total, limited, changedSinceAudit }: { findings: IsolationFinding[]; total: number; limited: boolean; changedSinceAudit: boolean }) {
  const navigate = useNavigate();
  const cut = total > findings.length;

  return (
    <Card>
      <CardHeader title="Open findings (live)" description="These are the issues open right now that put one tenant's content at risk of reaching another." />
      {changedSinceAudit ? (
        <div role="status" className="flex flex-wrap items-center gap-x-3 gap-y-2 border-b border-info/25 bg-info-bg px-5 py-3">
          <Info className="h-4 w-4 shrink-0 text-info" aria-hidden />
          <p className="min-w-0 flex-1 text-body text-ink">These changed since the last full audit. Run a full audit to refresh the summary above.</p>
          <RunFullAuditButton variant="secondary" size="sm" />
        </div>
      ) : null}
      {cut ? (
        <p className="border-b border-line bg-app px-4 py-2 text-support text-ink-2">
          Showing {formatNumber(findings.length)} of {formatNumber(total)} findings. The rest are in Integrity Issues.
        </p>
      ) : null}
      <DataTable
        label="Open tenant isolation findings"
        data={findings}
        columns={columns}
        getRowId={(f) => f.issue_id}
        onRowClick={(f) => navigate(links.issue(f.issue_id))}
        initialSort={[{ id: "severity", desc: true }]}
        empty={
          <EmptyState
            compact
            icon={ShieldCheck}
            title="No tenant isolation findings"
            description={
              limited
                ? "This check could not see vectors under another tenant, so an empty list does not prove isolation."
                : "No wrong-tenant issue and no permission mismatch is open right now."
            }
          />
        }
      />
      <div className="flex flex-wrap items-center gap-x-6 gap-y-2 border-t border-line px-5 py-3">
        <LinkButton variant="link" to={links.issues({ type: "tenant_mismatch" })}>
          Wrong-tenant issues
          <ArrowRight className="h-3.5 w-3.5" aria-hidden />
        </LinkButton>
        <LinkButton variant="link" to={links.issues({ type: "metadata_inconsistent" })}>
          Permission mismatches
          <ArrowRight className="h-3.5 w-3.5" aria-hidden />
        </LinkButton>
      </div>
    </Card>
  );
}
