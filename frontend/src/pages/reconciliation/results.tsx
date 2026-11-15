import { CircleCheck } from "lucide-react";
import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { LinkButton } from "@/components/shared/link-button";
import { SeverityBadge } from "@/components/shared/status";
import { cn } from "@/lib/cn";
import { formatNumber } from "@/lib/format";
import { issueLabel, SEVERITIES } from "@/lib/issue-meta";
import { links } from "@/lib/links";
import type { AuditRun, Severity } from "@/types/api";

const DIFF_ROWS = [
  { key: "opened", label: "Opened", note: "New issues", tone: "text-warning" },
  { key: "reopened", label: "Reopened", note: "Came back after being resolved", tone: "text-warning" },
  { key: "escalated", label: "Escalated", note: "Became more severe", tone: "text-warning" },
  { key: "resolved", label: "Resolved", note: "No longer found", tone: "text-success" },
  { key: "unchanged", label: "Unchanged", note: "Still open", tone: "text-ink" },
] as const;

function Column({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="min-w-0">
      <h3 className="table-head mb-3">{title}</h3>
      {children}
    </section>
  );
}

export function ResultsCard({ run }: { run: AuditRun }) {
  const s = run.stats;
  const total = s.findings_total;
  const bySeverity = s.findings_by_severity ?? {};
  const byType = Object.entries(s.findings_by_type ?? {})
    .filter(([, n]) => n > 0)
    .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
  const severities = (SEVERITIES as Severity[]).concat(bySeverity.info ? ["info"] : []).filter((k) => (bySeverity[k] ?? 0) > 0);
  const diff = s.diff;

  if (total === undefined && !diff) return null;

  return (
    <Card>
      <CardHeader
        title="Results of the latest full audit"
        description="What the comparison found, and what changed since the audit before it."
        actions={
          <LinkButton variant="secondary" size="sm" to={links.issues()}>
            View all issues
          </LinkButton>
        }
      />
      <CardBody className="grid gap-6 md:grid-cols-3">
        {total !== undefined ? (
          <Column title="Findings">
            <p className="text-kpi tabular-nums text-ink">{formatNumber(total)}</p>
            <p className="text-support text-ink-2">{total === 1 ? "issue found" : "issues found"}</p>
            {total === 0 ? (
              <p className="mt-3 flex items-center gap-2 text-body text-success">
                <CircleCheck className="h-4 w-4" aria-hidden /> Everything this audit compared agrees.
              </p>
            ) : (
              <ul className="mt-3 space-y-2">
                {severities.map((k) => (
                  <li key={k} className="flex items-center justify-between gap-3">
                    <Link to={links.issues({ severity: k })} className="rounded-full hover:opacity-80" aria-label={`${bySeverity[k]} ${k} issues. View them.`}>
                      <SeverityBadge severity={k} />
                    </Link>
                    <span className="text-body font-medium tabular-nums text-ink">{formatNumber(bySeverity[k])}</span>
                  </li>
                ))}
              </ul>
            )}
          </Column>
        ) : null}

        {total !== undefined && total > 0 ? (
          <Column title="By type">
            <ul className="space-y-1">
              {byType.map(([type, n]) => (
                <li key={type}>
                  <Link to={links.issues({ type })} className="-mx-2 flex items-center justify-between gap-3 rounded-control px-2 py-1.5 text-body hover:bg-surface-hover">
                    <span className="truncate text-ink" title={issueLabel(type)}>
                      {issueLabel(type)}
                    </span>
                    <span className="font-medium tabular-nums text-ink">{formatNumber(n)}</span>
                  </Link>
                </li>
              ))}
            </ul>
          </Column>
        ) : null}

        {diff ? (
          <Column title="Since the previous audit">
            <dl className="space-y-2">
              {DIFF_ROWS.map((r) => (
                <div key={r.key} className="flex items-baseline justify-between gap-3">
                  <dt className="min-w-0">
                    <span className="text-body text-ink">{r.label}</span>
                    <span className="ml-2 hidden text-support text-ink-2 xl:inline">{r.note}</span>
                  </dt>
                  <dd className={cn("text-body font-medium tabular-nums", diff[r.key] > 0 ? r.tone : "text-ink-2")}>{formatNumber(diff[r.key])}</dd>
                </div>
              ))}
            </dl>
          </Column>
        ) : null}
      </CardBody>
    </Card>
  );
}
