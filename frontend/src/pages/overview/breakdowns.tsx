import { Link } from "react-router-dom";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { ProgressBar } from "@/components/shared/page";
import { formatNumber } from "@/lib/format";
import { issueLabel } from "@/lib/issue-meta";
import { links } from "@/lib/links";
import { cn } from "@/lib/cn";
import type { Overview } from "@/types/api";
import { SrTable } from "./ui";

// ---- issues by type -------------------------------------------------------------------------------------
export function IssuesByTypeCard({ byType, className }: { byType: Overview["issues"]["by_type"]; className?: string }) {
  const rows = Object.entries(byType)
    .filter(([, n]) => n > 0)
    .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
  const max = rows[0]?.[1] ?? 1;

  return (
    <Card className={cn("min-w-0", className)}>
      <CardHeader title="Issues by type" description="What is wrong, across all open issues. Select one to see those issues." />
      <CardBody className="space-y-1 py-3">
        {rows.map(([type, n]) => (
          <Link
            key={type}
            to={links.issues({ type })}
            className="group -mx-2 grid grid-cols-[minmax(0,8.5rem)_minmax(0,1fr)_2.5rem] items-center gap-3 rounded-control px-2 py-2 hover:bg-surface-hover sm:grid-cols-[minmax(0,12rem)_minmax(0,1fr)_2.5rem]"
          >
            <span className="truncate text-body text-ink group-hover:text-brand" title={issueLabel(type)}>
              {issueLabel(type)}
            </span>
            <ProgressBar value={(n / max) * 100} tone="brand" label={`${issueLabel(type)}: ${n} open`} />
            <span className="text-right text-body font-medium tabular-nums text-ink">{formatNumber(n)}</span>
          </Link>
        ))}
      </CardBody>
    </Card>
  );
}

// ---- document status --------------------------------------------------------------------------------------
const STATUSES = [
  { key: "healthy", label: "Healthy", note: "Source, manifest and index agree", bar: "bg-success" },
  { key: "degraded", label: "Degraded", note: "Searchable, with minor issues", bar: "bg-warning" },
  { key: "broken", label: "Broken", note: "Serious issues found", bar: "bg-critical" },
  { key: "pending", label: "Pending", note: "Still being processed", bar: "bg-info" },
  { key: "orphaned", label: "Orphaned", note: "Deleted at the source, vectors remain", bar: "bg-ink-3" },
] as const;

export function DocumentStatusCard({ byStatus, total, className }: { byStatus: Overview["documents"]["by_status"]; total: number; className?: string }) {
  const rows = STATUSES.map((s) => ({ ...s, count: byStatus[s.key] ?? 0 }));
  const summary = rows.filter((r) => r.count > 0).map((r) => `${formatNumber(r.count)} ${r.label.toLowerCase()}`).join(", ");

  return (
    <Card className={cn("min-w-0", className)}>
      <CardHeader title="Document status" description="Where every document stands after the last audit." />
      <CardBody>
        <div className="flex h-3 w-full overflow-hidden rounded-full bg-surface" role="img" aria-label={`Document status: ${summary}`}>
          {rows
            .filter((r) => r.count > 0)
            .map((r) => (
              <div key={r.key} className={cn("h-full", r.bar)} style={{ width: `${(r.count / total) * 100}%` }} title={`${r.label}: ${formatNumber(r.count)}`} />
            ))}
        </div>
        <ul className="mt-4 divide-y divide-line">
          {rows.map((r) => (
            <li key={r.key}>
              <Link
                to={links.documents({ status: r.key })}
                className="-mx-2 flex items-center gap-3 rounded-control px-2 py-2.5 hover:bg-surface-hover"
                aria-label={`${r.label}: ${r.count} documents. View them.`}
              >
                <span className={cn("h-2.5 w-2.5 shrink-0 rounded-sm", r.bar)} aria-hidden />
                <span className="min-w-0 flex-1">
                  <span className="block text-body text-ink">{r.label}</span>
                  <span className="block truncate text-support text-ink-2">{r.note}</span>
                </span>
                <span className="font-medium tabular-nums text-ink">{formatNumber(r.count)}</span>
                <span className="w-12 text-right text-support tabular-nums text-ink-2">{((r.count / total) * 100).toFixed(1)}%</span>
              </Link>
            </li>
          ))}
        </ul>
        <SrTable caption="Documents by status" columns={["Status", "Documents"]} rows={rows.map((r) => [r.label, r.count])} />
      </CardBody>
    </Card>
  );
}
