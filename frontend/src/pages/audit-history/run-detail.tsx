import type { ColumnDef } from "@tanstack/react-table";
import { ArrowLeft, CircleCheck, FileQuestion, Loader2, TriangleAlert } from "lucide-react";
import { useMemo, type ReactNode } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { DataTable } from "@/components/shared/data-table";
import { KpiCard, PageHeader } from "@/components/shared/page";
import { EmptyState, ErrorState, Skeleton } from "@/components/shared/states";
import { CopyButton } from "@/components/shared/copy-button";
import { LinkButton } from "@/components/shared/link-button";
import { RunWarningsSection, runWarnings } from "@/components/shared/run-warnings";
import { IssueStatusBadge, RunStatusBadge, SeverityBadge, healthTone } from "@/components/shared/status";
import { useAudit, useIssues, useOverview } from "@/hooks/queries";
import { useRunAudit } from "@/hooks/use-run-audit";
import { ApiError } from "@/lib/api";
import { cn } from "@/lib/cn";
import { formatDateTime, formatDuration, formatNumber, formatPercent, shortHash, timeAgo } from "@/lib/format";
import { issueLabel, severityRank, SEVERITIES } from "@/lib/issue-meta";
import { links } from "@/lib/links";
import type { AuditRun, Issue, Severity } from "@/types/api";
import { documentLabel, humanize, kindLabel, scopeLabel } from "./helpers";

const ISSUE_LIMIT = 500;

const HEALTH_TEXT = { success: "text-success", warning: "text-warning", critical: "text-critical", neutral: "text-ink", brand: "text-ink", info: "text-ink" } as const;

const DIFF_ROWS = [
  { key: "opened", label: "Opened", tone: "text-warning" },
  { key: "reopened", label: "Reopened", tone: "text-warning" },
  { key: "escalated", label: "Escalated", tone: "text-warning" },
  { key: "resolved", label: "Resolved", tone: "text-success" },
  { key: "unchanged", label: "Unchanged", tone: "text-ink" },
] as const;

/** Continues a partial audit from its checkpoint. Only offered while this run is still the one that can be resumed. */
function ResumeButton({ run }: { run: AuditRun }) {
  const { run: start, running } = useRunAudit();
  const resumable = useOverview(true).data?.resumable_audit;
  const can = resumable?.run_id === run.id;
  return (
    <div className="mt-3">
      <Button variant="primary" size="sm" disabled={!can || running} loading={running} onClick={() => start({ resume: true })}>
        Resume audit
      </Button>
      {!can ? <p className="mt-1.5 text-support text-ink-2">This audit has already been resumed, or a newer audit replaced it.</p> : null}
    </div>
  );
}

function BackLink() {
  return (
    <LinkButton variant="ghost" size="sm" to="/audit-history" className="-ml-2 mb-3">
      <ArrowLeft className="h-4 w-4" aria-hidden /> Back to audit history
    </LinkButton>
  );
}

export function RunDetail({ runId }: { runId: string }) {
  const q = useAudit(runId);

  if (q.isPending) {
    return (
      <div aria-busy aria-label="Loading audit">
        <BackLink />
        <Skeleton className="h-8 w-64" />
        <Skeleton className="mt-2 h-4 w-96 max-w-full" />
        <div className="mt-6 grid gap-4 sm:grid-cols-2 xl:grid-cols-6">
          {[0, 1, 2, 3, 4, 5].map((i) => (
            <Skeleton key={i} className="h-[104px]" />
          ))}
        </div>
      </div>
    );
  }

  if (q.isError) {
    const notFound = q.error instanceof ApiError && q.error.status === 404;
    return (
      <div>
        <BackLink />
        <Card>
          {notFound ? (
            <EmptyState
              icon={FileQuestion}
              title="Audit not found"
              description="No audit has this id. It may belong to another workspace, or the link may be wrong."
              action={
                <LinkButton variant="primary" to="/audit-history">
                  Back to audit history
                </LinkButton>
              }
            />
          ) : (
            <ErrorState error={q.error} onRetry={() => void q.refetch()} />
          )}
        </Card>
      </div>
    );
  }

  return <RunView run={q.data} />;
}

function Meta({ label, children }: { label: string; children: ReactNode }) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <span className="text-ink-3">{label}</span>
      <span className="text-ink">{children}</span>
    </span>
  );
}

function RunView({ run }: { run: AuditRun }) {
  const s = run.stats;
  const running = run.status === "running";
  const failed = run.status === "failed";

  const statTiles: { label: string; value: ReactNode; hint?: string }[] = [];
  if (s.documents_total !== undefined) statTiles.push({ label: "Documents", value: formatNumber(s.documents_total), hint: "compared in total" });
  if (s.source_documents !== undefined) statTiles.push({ label: "Source documents", value: formatNumber(s.source_documents), hint: "in Amazon S3" });
  if (s.manifest_rows !== undefined) statTiles.push({ label: "Manifest rows", value: formatNumber(s.manifest_rows), hint: "in PostgreSQL" });
  if (s.index_points !== undefined) statTiles.push({ label: "Index vectors", value: formatNumber(s.index_points), hint: "in Qdrant" });
  if (s.retrieval_probes !== undefined) statTiles.push({ label: "Retrieval probes", value: formatNumber(s.retrieval_probes), hint: "queries sent to the index" });
  if (s.health_score !== undefined) {
    statTiles.push({
      label: "Health score",
      value: <span className={HEALTH_TEXT[healthTone(s.health_score)]}>{formatPercent(s.health_score)}</span>,
      hint: "of documents are healthy",
    });
  }

  const bySeverity = s.findings_by_severity ?? {};
  const severities = (SEVERITIES as Severity[]).concat(bySeverity.info ? ["info"] : []).filter((k) => (bySeverity[k] ?? 0) > 0);
  const byType = Object.entries(s.findings_by_type ?? {})
    .filter(([, n]) => n > 0)
    .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
  const showFindings = s.findings_total !== undefined;
  const diff = s.diff;
  const alerts = s.alerts;
  const tenantScope = s.scope?.tenant ?? run.scope.tenant;

  return (
    <div>
      <BackLink />
      <PageHeader
        title={`Audit ${shortHash(run.id, 8)}`}
        description={
          <span className="flex flex-wrap items-center gap-x-4 gap-y-1.5 text-support">
            <RunStatusBadge status={run.status} />
            <Meta label="Type">{kindLabel(run.kind)}</Meta>
            <Meta label="Trigger">{humanize(run.trigger)}</Meta>
            <Meta label="Scope">{scopeLabel(run)}</Meta>
            <Meta label="Started">{formatDateTime(run.started_at)}</Meta>
            {run.finished_at ? <Meta label="Finished">{formatDateTime(run.finished_at)}</Meta> : null}
            {s.duration_seconds !== undefined ? <Meta label="Duration">{formatDuration(s.duration_seconds)}</Meta> : null}
          </span>
        }
        actions={<CopyButton text={run.id} label="Copy run id" />}
      />

      <div className="space-y-6">
        {running ? (
          <div className="flex items-start gap-3 rounded-card border border-info/25 bg-info-bg px-4 py-3" role="status">
            <Loader2 className="mt-0.5 h-4 w-4 shrink-0 animate-spin text-info" aria-hidden />
            <p className="text-body text-ink">
              This audit is still running. It started {timeAgo(run.started_at)}, and this page updates when it finishes.
            </p>
          </div>
        ) : null}

        {run.status === "partial" ? (
          <div className="rounded-card border border-warning/30 bg-warning-bg px-4 py-3" role="note">
            <p className="flex items-center gap-2 text-card text-ink">
              <TriangleAlert className="h-4 w-4 text-warning" aria-hidden /> This audit stopped part-way
            </p>
            <p className="mt-1 break-words text-body text-ink">
              {s.scan?.documents_total
                ? `It checked ${formatNumber(s.scan.documents_done ?? 0)} of ${formatNumber(s.scan.documents_total)} documents (${formatPercent(s.scan.percent ?? 0)}). What it checked is reported; the rest is not, so nothing is claimed about it. `
                : "What it checked is reported; the rest is not. "}
              {s.scan?.stopped_because ? `Why it stopped: ${s.scan.stopped_because}. ` : ""}
              Resume it to continue from the last checkpoint.
            </p>
            <ResumeButton run={run} />
          </div>
        ) : null}

        {failed ? (
          <div className="rounded-card border border-critical/25 bg-critical-bg px-4 py-3" role="alert">
            <p className="flex items-center gap-2 text-card text-critical">
              <TriangleAlert className="h-4 w-4" aria-hidden /> This audit failed
            </p>
            <p className="mt-1 break-words text-body text-ink">{run.error ?? "The audit stopped without recording a reason."}</p>
          </div>
        ) : null}

        {statTiles.length > 0 ? (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6">
            {statTiles.map((t) => (
              <KpiCard key={t.label} label={t.label} value={t.value} hint={t.hint} />
            ))}
          </div>
        ) : null}

        <RunWarningsSection warnings={runWarnings(s)} />

        {diff || showFindings ? (
          <div className="grid gap-4 lg:grid-cols-2">
            {diff ? (
              <Card className="min-w-0">
                <CardHeader title="Changes in this audit" description="Compared with the audit before it." />
                <dl className="divide-y divide-line px-5">
                  {DIFF_ROWS.map((r) => (
                    <div key={r.key} className="flex items-center justify-between py-3">
                      <dt className="text-body text-ink-2">{r.label}</dt>
                      <dd className={cn("text-body font-medium tabular-nums", diff[r.key] > 0 ? r.tone : "text-ink-2")}>{formatNumber(diff[r.key])}</dd>
                    </div>
                  ))}
                </dl>
              </Card>
            ) : null}

            {showFindings ? (
              <Card className="min-w-0">
                <CardHeader
                  title="Findings"
                  description={`${formatNumber(s.findings_total)} ${s.findings_total === 1 ? "issue" : "issues"} found${tenantScope ? ` for tenant ${tenantScope}` : ""}.`}
                />
                {s.findings_total === 0 ? (
                  <EmptyState compact icon={CircleCheck} title="No integrity issues" description="Everything this audit checked agreed across the source, manifest and index." />
                ) : (
                  <CardBody className="grid gap-6 sm:grid-cols-2">
                    <section className="min-w-0">
                      <h3 className="table-head mb-3">By severity</h3>
                      <ul className="space-y-2">
                        {severities.map((k) => (
                          <li key={k} className="flex items-center justify-between gap-3">
                            <SeverityBadge severity={k} />
                            <span className="text-body font-medium tabular-nums text-ink">{formatNumber(bySeverity[k])}</span>
                          </li>
                        ))}
                      </ul>
                    </section>
                    <section className="min-w-0">
                      <h3 className="table-head mb-3">By type</h3>
                      <ul className="space-y-1">
                        {byType.map(([type, n]) => (
                          <li key={type}>
                            <Link to={links.issues({ type })} className="-mx-2 flex items-center justify-between gap-3 rounded-control px-2 py-1 text-body hover:bg-surface-hover">
                              <span className="truncate text-ink" title={issueLabel(type)}>
                                {issueLabel(type)}
                              </span>
                              <span className="font-medium tabular-nums text-ink">{formatNumber(n)}</span>
                            </Link>
                          </li>
                        ))}
                      </ul>
                    </section>
                  </CardBody>
                )}
              </Card>
            ) : null}
          </div>
        ) : null}

        {alerts && (alerts.sent !== undefined || alerts.issues !== undefined || alerts.reason || alerts.error) ? (
          <Card>
            <CardHeader title="Alert delivery" description="Whether this audit sent an alert about what it found." />
            <CardBody>
              <dl className="grid gap-x-6 gap-y-3 sm:grid-cols-3">
                {alerts.sent !== undefined ? (
                  <div>
                    <dt className="text-support text-ink-2">Alerts sent</dt>
                    <dd className="mt-0.5 text-body tabular-nums text-ink">{formatNumber(alerts.sent)}</dd>
                  </div>
                ) : null}
                {alerts.issues !== undefined ? (
                  <div>
                    <dt className="text-support text-ink-2">Issues included</dt>
                    <dd className="mt-0.5 text-body tabular-nums text-ink">{formatNumber(alerts.issues)}</dd>
                  </div>
                ) : null}
                {alerts.reason ? (
                  <div className="min-w-0">
                    <dt className="text-support text-ink-2">Reason</dt>
                    <dd className="mt-0.5 break-words text-body text-ink">{humanize(alerts.reason)}</dd>
                  </div>
                ) : null}
              </dl>
              {alerts.error ? (
                <p className="mt-4 break-words rounded-control bg-critical-bg px-3 py-2 text-support text-critical" role="alert">
                  Delivery failed: {alerts.error}
                </p>
              ) : null}
            </CardBody>
          </Card>
        ) : null}

        {running ? null : <RunIssues runId={run.id} />}
      </div>
    </div>
  );
}

// ---- the issues this run opened and resolved -------------------------------------------------------------------
const issueColumns: ColumnDef<Issue>[] = [
  { id: "severity", header: "Severity", accessorFn: (i) => i.severity, sortingFn: (a, b) => severityOrder(a.original) - severityOrder(b.original), cell: ({ row }) => <SeverityBadge severity={row.original.severity} /> },
  {
    id: "issue",
    header: "Issue",
    accessorFn: (i) => i.title,
    cell: ({ row }) => (
      <div className="min-w-0 max-w-[420px]">
        <p className="truncate font-medium text-ink" title={row.original.title}>
          {row.original.title}
        </p>
        <p className="truncate text-support text-ink-2">{issueLabel(row.original.type)}</p>
      </div>
    ),
  },
  {
    id: "document",
    header: "Document",
    accessorFn: (i) => i.document_id,
    cell: ({ row }) => (
      <span className="block max-w-[240px] truncate text-ink-2" title={row.original.document_id}>
        {documentLabel(row.original.document_id)}
      </span>
    ),
  },
  { id: "tenant", header: "Tenant", accessorFn: (i) => i.tenant_id, cell: ({ row }) => <span className="block max-w-[140px] truncate text-ink-2" title={row.original.tenant_id}>{row.original.tenant_id}</span> },
  { id: "status", header: "Now", accessorFn: (i) => i.status, cell: ({ row }) => <IssueStatusBadge status={row.original.status} /> },
];

const severityOrder = (i: Issue): number => severityRank[i.severity];

function RunIssues({ runId }: { runId: string }) {
  const navigate = useNavigate();
  const q = useIssues({ status: "all", limit: ISSUE_LIMIT });

  const opened = useMemo(() => (q.data?.items ?? []).filter((i) => i.first_run_id === runId), [q.data, runId]);
  const resolved = useMemo(() => (q.data?.items ?? []).filter((i) => i.resolved_run_id === runId), [q.data, runId]);
  const truncated = q.data && q.data.total > q.data.items.length ? `Based on the first ${formatNumber(q.data.items.length)} of ${formatNumber(q.data.total)} issues.` : undefined;

  if (q.isError) {
    return (
      <Card>
        <ErrorState error={q.error} onRetry={() => void q.refetch()} />
      </Card>
    );
  }

  const table = (title: string, description: string, rows: Issue[], emptyTitle: string, emptyText: string) => (
    <Card>
      <CardHeader title={title} description={description} />
      <DataTable
        label={title}
        data={rows}
        columns={issueColumns}
        loading={q.isPending}
        getRowId={(i) => i.id}
        onRowClick={(i) => navigate(links.issue(i.id))}
        initialSort={[{ id: "severity", desc: true }]}
        pageSize={10}
        note={truncated}
        skeletonRows={3}
        empty={<EmptyState compact icon={CircleCheck} title={emptyTitle} description={emptyText} />}
      />
    </Card>
  );

  return (
    <>
      {table("New in this run", "Issues this audit found for the first time.", opened, "No new issues", "This audit did not open any issue that was not already known.")}
      {table("Resolved in this run", "Issues that were open before and that this audit no longer found.", resolved, "Nothing resolved", "This audit did not close any issue.")}
    </>
  );
}
