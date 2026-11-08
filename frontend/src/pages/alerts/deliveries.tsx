import type { ColumnDef } from "@tanstack/react-table";
import { Bell } from "lucide-react";
import { useMemo } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { Badge, type Tone } from "@/components/ui/badge";
import { Card, CardHeader } from "@/components/ui/card";
import { DataTable } from "@/components/shared/data-table";
import { FilterBar, FilterSelect } from "@/components/shared/filters";
import { EmptyState, ErrorState } from "@/components/shared/states";
import { useAudits } from "@/hooks/queries";
import { formatDateTime, formatNumber, timeAgo } from "@/lib/format";
import { links } from "@/lib/links";
import type { AuditRun, AuditStats } from "@/types/api";

type Outcome = "delivered" | "failed" | "skipped";
type Alerts = NonNullable<AuditStats["alerts"]>;
interface Row {
  run: AuditRun;
  alerts: Alerts;
  outcome: Outcome;
}

const OUTCOME: Record<Outcome, { label: string; tone: Tone }> = {
  delivered: { label: "Delivered", tone: "success" },
  failed: { label: "Failed", tone: "critical" },
  skipped: { label: "Not sent", tone: "neutral" },
};

const FILTERS = [
  { value: "attempted", label: "Delivered or failed" },
  { value: "all", label: "Every audit" },
  { value: "delivered", label: "Delivered" },
  { value: "failed", label: "Failed" },
  { value: "skipped", label: "Not sent" },
];

const outcomeOf = (a: Alerts): Outcome => ((a.sent ?? 0) > 0 ? "delivered" : a.error ? "failed" : "skipped");

/** The server's reasons are written for the single-user setup; say the same thing in plain words. */
function describe(row: Row): string {
  const { alerts, outcome } = row;
  if (outcome === "delivered") return "Sent to the alert webhook.";
  if (outcome === "failed") return alerts.error ?? "The webhook did not accept the message.";
  const reason = alerts.reason ?? "";
  if (/no .*webhook/i.test(reason)) return "No alert webhook was configured.";
  if (/no new issues/i.test(reason)) return "No new issues at or above the minimum severity.";
  return reason || "Nothing to send.";
}

export function RecentDeliveries() {
  const audits = useAudits(50);
  const [params, setParams] = useSearchParams();
  const filter = FILTERS.some((f) => f.value === params.get("outcome")) ? (params.get("outcome") as string) : "attempted";

  const all = useMemo<Row[]>(
    () =>
      (audits.data ?? [])
        .filter((r) => !!r.stats?.alerts)
        .map((r) => {
          const alerts = r.stats.alerts as Alerts;
          return { run: r, alerts, outcome: outcomeOf(alerts) };
        }),
    [audits.data],
  );
  const rows = useMemo(() => all.filter((r) => (filter === "all" ? true : filter === "attempted" ? r.outcome !== "skipped" : r.outcome === filter)), [all, filter]);

  function setFilter(v: string) {
    const next = new URLSearchParams(params);
    if (v === "attempted") next.delete("outcome");
    else next.set("outcome", v);
    setParams(next, { replace: true });
  }

  const columns = useMemo<ColumnDef<Row>[]>(
    () => [
      {
        id: "started_at",
        header: "Audit run",
        accessorFn: (r) => r.run.started_at,
        cell: (c) => {
          const { run } = c.row.original;
          return (
            <div>
              <Link to={links.audit(run.id)} className="font-medium text-brand hover:underline">{formatDateTime(run.started_at)}</Link>
              <p className="text-support text-ink-2">{run.kind.charAt(0).toUpperCase() + run.kind.slice(1)} audit, {timeAgo(run.started_at)}</p>
            </div>
          );
        },
      },
      {
        id: "outcome",
        header: "Outcome",
        accessorFn: (r) => r.outcome,
        cell: (c) => <Badge tone={OUTCOME[c.row.original.outcome].tone} dot>{OUTCOME[c.row.original.outcome].label}</Badge>,
      },
      {
        id: "issues",
        header: "Issues included",
        accessorFn: (r) => r.alerts.issues ?? 0,
        meta: { className: "tabular-nums" },
        cell: (c) => (c.row.original.alerts.issues ? formatNumber(c.row.original.alerts.issues) : <span className="text-ink-3">None</span>),
      },
      {
        id: "detail",
        header: "Detail",
        enableSorting: false,
        meta: { className: "min-w-[260px]" },
        cell: (c) => <span className={c.row.original.outcome === "failed" ? "break-words text-critical" : "text-ink-2"}>{describe(c.row.original)}</span>,
      },
    ],
    [],
  );

  return (
    <Card>
      <CardHeader title="Recent deliveries" description="What happened to the alert after each of the latest audits." />
      <FilterBar active={filter !== "attempted"} onClear={() => setFilter("attempted")}>
        <FilterSelect label="Show" value={filter} onChange={setFilter} options={FILTERS} />
      </FilterBar>
      {audits.isError ? (
        <ErrorState error={audits.error} onRetry={() => void audits.refetch()} compact />
      ) : (
        <DataTable
          label="Recent alert deliveries"
          data={rows}
          columns={columns}
          loading={audits.isPending}
          getRowId={(r) => r.run.id}
          initialSort={[{ id: "started_at", desc: true }]}
          pageSize={10}
          note="From the latest 50 audits."
          empty={
            all.length === 0 || filter === "attempted" ? (
              <EmptyState
                compact
                icon={Bell}
                title="No alerts have been sent yet"
                description={
                  all.length > 0
                    ? "Audits have run, but none produced an alert. Choose Every audit to see why."
                    : "After every audit RAGGuard checks for new issues. Once an alert webhook is saved and an audit finds something new, each delivery is listed here."
                }
              />
            ) : (
              <EmptyState compact icon={Bell} title="No audits match this filter" description="Choose another outcome to see more." />
            )
          }
        />
      )}
    </Card>
  );
}
