import { ChevronRight, CircleCheck } from "lucide-react";
import { useMemo } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Card, CardHeader } from "@/components/ui/card";
import { EmptyState, ErrorState, Skeleton } from "@/components/shared/states";
import { HealthBadge, RunStatusBadge, SeverityBadge } from "@/components/shared/status";
import { useConnections, useIssues } from "@/hooks/queries";
import { cn } from "@/lib/cn";
import { formatDateTime, formatNumber, timeAgo } from "@/lib/format";
import { severityRank } from "@/lib/issue-meta";
import { links } from "@/lib/links";
import type { AuditRun, TenantHealth } from "@/types/api";
import { CardFooterLink, capitalize, documentLabel } from "./ui";

// ---- top open issues ----------------------------------------------------------------------------------
export function TopIssuesCard() {
  const q = useIssues({ status: "open", limit: 100 });
  const top = useMemo(
    () =>
      q.data
        ? [...q.data.items]
            .sort((a, b) => severityRank[b.severity] - severityRank[a.severity] || Date.parse(b.last_seen_at) - Date.parse(a.last_seen_at))
            .slice(0, 6)
        : [],
    [q.data],
  );

  return (
    <Card className="min-w-0">
      <CardHeader title="Top open issues" description="Most serious first, then most recently seen." />
      {q.isPending ? (
        <ul className="divide-y divide-line" aria-busy aria-label="Loading issues">
          {Array.from({ length: 6 }).map((_, i) => (
            <li key={i} className="flex items-center gap-3 px-5 py-3">
              <Skeleton className="h-5 w-[72px]" />
              <div className="flex-1 space-y-1.5">
                <Skeleton className="h-4 w-2/3" />
                <Skeleton className="h-3 w-1/3" />
              </div>
            </li>
          ))}
        </ul>
      ) : q.isError ? (
        <ErrorState compact error={q.error} onRetry={() => void q.refetch()} />
      ) : top.length === 0 ? (
        <EmptyState compact icon={CircleCheck} title="No open issues" description="Nothing needs attention right now." />
      ) : (
        <>
          <ul className="divide-y divide-line">
            {top.map((i) => (
              <li key={i.id}>
                <Link to={links.issue(i.id)} className="flex items-center gap-3 px-5 py-3 hover:bg-surface-hover focus-visible:bg-surface-hover">
                  <span className="w-[88px] shrink-0">
                    <SeverityBadge severity={i.severity} />
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-body font-medium text-ink" title={i.title}>
                      {i.title}
                    </span>
                    <span className="block truncate text-support text-ink-2" title={`${i.document_id} in ${i.tenant_id}`}>
                      {documentLabel(i.document_id)} · {i.tenant_id}
                    </span>
                  </span>
                  <span className="hidden shrink-0 text-support text-ink-2 sm:block" title={formatDateTime(i.last_seen_at)}>
                    {timeAgo(i.last_seen_at)}
                  </span>
                  <ChevronRight className="h-4 w-4 shrink-0 text-ink-3" aria-hidden />
                </Link>
              </li>
            ))}
          </ul>
          <CardFooterLink to={links.issues()}>View all {formatNumber(q.data.total)} open issues</CardFooterLink>
        </>
      )}
    </Card>
  );
}

// ---- tenant health ------------------------------------------------------------------------------------
const TENANT_ROWS = 8;

export function TenantHealthCard({ tenants }: { tenants: TenantHealth[] }) {
  const navigate = useNavigate();
  // worst first: that is the order you want to act in; tenants without a score go last
  const sorted = [...tenants].sort((a, b) => (a.health_score ?? 101) - (b.health_score ?? 101) || a.tenant_id.localeCompare(b.tenant_id));
  const shown = sorted.slice(0, TENANT_ROWS);

  return (
    <Card className="min-w-0">
      <CardHeader title="Tenant health" description="Share of each tenant's documents that are healthy, lowest first." />
      <div className="overflow-x-auto">
        <table className="w-full min-w-[420px] border-collapse text-table" aria-label="Tenant health">
          <thead>
            <tr className="border-b border-line bg-app">
              <th scope="col" className="table-head px-5 py-2.5 text-left">Tenant</th>
              <th scope="col" className="table-head px-4 py-2.5 text-right">Documents</th>
              <th scope="col" className="table-head px-4 py-2.5 text-right">Healthy</th>
              <th scope="col" className="table-head px-5 py-2.5 text-right">Health</th>
            </tr>
          </thead>
          <tbody>
            {shown.map((t) => (
              <tr key={t.tenant_id} onClick={() => navigate(links.documents({ tenant: t.tenant_id }))} className="cursor-pointer border-b border-line last:border-0 hover:bg-surface-hover">
                <td className="max-w-[240px] px-5 py-3">
                  <Link to={links.documents({ tenant: t.tenant_id })} className="block truncate font-medium text-ink hover:text-brand" title={t.tenant_id} onClick={(e) => e.stopPropagation()}>
                    {t.tenant_id}
                  </Link>
                </td>
                <td className="px-4 py-3 text-right tabular-nums text-ink">{formatNumber(t.documents)}</td>
                <td className="px-4 py-3 text-right tabular-nums text-ink">{formatNumber(t.healthy)}</td>
                <td className="px-5 py-3 text-right">
                  <HealthBadge score={t.health_score} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {sorted.length > TENANT_ROWS ? <CardFooterLink to={links.documents()}>View all {formatNumber(sorted.length)} tenants</CardFooterLink> : null}
    </Card>
  );
}

// ---- last audit ----------------------------------------------------------------------------------------
const DIFF_ROWS = [
  { key: "opened", label: "Opened", hot: true },
  { key: "reopened", label: "Reopened", hot: true },
  { key: "escalated", label: "Escalated", hot: true },
  { key: "resolved", label: "Resolved", hot: false },
  { key: "unchanged", label: "Unchanged", hot: false },
] as const;

export function LastAuditCard({ run }: { run: AuditRun }) {
  const stats = run.stats;
  const diff = stats.diff;
  const when = run.finished_at ?? run.started_at;

  return (
    <Card className="min-w-0">
      <CardHeader title="Last audit" description={`${capitalize(run.kind)} audit, ${timeAgo(when)}`} actions={<RunStatusBadge status={run.status} />} />
      <div className="space-y-3 px-5 py-4">
        {run.status === "failed" && run.error ? (
          <p className="rounded-control bg-critical-bg px-3 py-2 text-support text-critical" role="alert">
            {run.error}
          </p>
        ) : null}
        {diff || stats.retrieval_probes !== undefined ? (
          <dl className="divide-y divide-line">
            {diff
              ? DIFF_ROWS.map((r) => (
                  <div key={r.key} className="flex items-center justify-between py-2 first:pt-0">
                    <dt className="text-body text-ink-2">{r.label}</dt>
                    <dd className={cn("text-body font-medium tabular-nums", diff[r.key] > 0 ? (r.hot ? "text-warning" : r.key === "resolved" ? "text-success" : "text-ink") : "text-ink")}>
                      {formatNumber(diff[r.key])}
                    </dd>
                  </div>
                ))
              : null}
            {stats.retrieval_probes !== undefined ? (
              <div className={cn("flex items-center justify-between py-2", !diff && "pt-0")}>
                <dt className="text-body text-ink-2">Retrieval probes</dt>
                <dd className="text-body font-medium tabular-nums text-ink">{formatNumber(stats.retrieval_probes)}</dd>
              </div>
            ) : null}
          </dl>
        ) : run.status === "running" ? (
          <p className="text-body text-ink-2">This audit is still running.</p>
        ) : null}
      </div>
      <CardFooterLink to={links.audit(run.id)}>View audit details</CardFooterLink>
    </Card>
  );
}

// ---- connection health ----------------------------------------------------------------------------------
export function ConnectionHealthCard() {
  const q = useConnections();

  return (
    <Card className="min-w-0">
      <CardHeader title="Connection health" description="Checked live from the server." />
      {q.isPending ? (
        <ul className="divide-y divide-line" aria-busy aria-label="Checking connections">
          {Array.from({ length: 4 }).map((_, i) => (
            <li key={i} className="flex items-center gap-3 px-5 py-3">
              <Skeleton className="h-2.5 w-2.5 rounded-full" />
              <div className="flex-1 space-y-1.5">
                <Skeleton className="h-4 w-1/2" />
                <Skeleton className="h-3 w-3/4" />
              </div>
            </li>
          ))}
        </ul>
      ) : q.isError ? (
        <ErrorState compact error={q.error} onRetry={() => void q.refetch()} />
      ) : (
        <ul className="divide-y divide-line">
          {q.data.map((c) => (
            <li key={`${c.kind}-${c.name}`} className="flex items-center gap-3 px-5 py-3">
              <span className={cn("h-2.5 w-2.5 shrink-0 rounded-full", c.ok ? "bg-success" : "bg-critical")} aria-hidden />
              <div className="min-w-0 flex-1">
                <p className="truncate text-body font-medium text-ink">
                  {c.name}
                  <span className="sr-only">{c.ok ? ": connected" : ": not responding"}</span>
                </p>
                <p className={cn("truncate text-support", c.ok ? "text-ink-2" : "text-critical")} title={c.detail}>
                  {c.detail}
                </p>
              </div>
              {c.latency_ms !== null ? <span className="shrink-0 text-support tabular-nums text-ink-2">{Math.round(c.latency_ms)} ms</span> : null}
            </li>
          ))}
        </ul>
      )}
      <CardFooterLink to="/data-sources">Manage data sources</CardFooterLink>
    </Card>
  );
}
