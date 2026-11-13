import type { ColumnDef } from "@tanstack/react-table";
import { History } from "lucide-react";
import { useMemo } from "react";
import { useNavigate } from "react-router-dom";
import { Card } from "@/components/ui/card";
import { SearchInput } from "@/components/ui/form";
import { DataTable } from "@/components/shared/data-table";
import { FilterBar, FilterSelect } from "@/components/shared/filters";
import { EmptyState, ErrorState } from "@/components/shared/states";
import { HealthBadge, RunStatusBadge } from "@/components/shared/status";
import { LinkButton } from "@/components/shared/link-button";
import { useAudits } from "@/hooks/queries";
import { formatDateTime, formatDuration, formatNumber, shortHash } from "@/lib/format";
import { links } from "@/lib/links";
import { cn } from "@/lib/cn";
import type { AuditRun } from "@/types/api";
import { humanize, kindLabel, scopeLabel } from "./helpers";
import { useClearParams, useUrlParam, useUrlSearch } from "./use-url-state";

const STATUS_OPTIONS = [
  { value: "", label: "All statuses" },
  { value: "running", label: "Running" },
  { value: "completed", label: "Completed" },
  { value: "partial", label: "Partial" },
  { value: "failed", label: "Failed" },
];
const KIND_OPTIONS = [
  { value: "", label: "All types" },
  { value: "full", label: "Full" },
  { value: "scoped", label: "Scoped" },
  { value: "verify", label: "Verify" },
];

const num = "text-right tabular-nums";

const columns: ColumnDef<AuditRun>[] = [
  {
    id: "started",
    header: "Started",
    accessorFn: (r) => r.started_at,
    cell: ({ row }) => (
      <div className="min-w-0">
        <p className="whitespace-nowrap text-ink">{formatDateTime(row.original.started_at)}</p>
        <p className="font-mono text-support text-ink-2" title={row.original.id}>
          {shortHash(row.original.id, 8)}
        </p>
      </div>
    ),
  },
  { id: "type", header: "Type", accessorFn: (r) => r.kind, cell: ({ row }) => <span className="whitespace-nowrap">{kindLabel(row.original.kind)}</span> },
  { id: "trigger", header: "Trigger", accessorFn: (r) => r.trigger, cell: ({ row }) => <span className="whitespace-nowrap text-ink-2">{humanize(row.original.trigger)}</span> },
  {
    id: "scope",
    header: "Scope",
    accessorFn: (r) => scopeLabel(r),
    cell: ({ row }) => (
      <span className="block max-w-[160px] truncate text-ink-2" title={scopeLabel(row.original)}>
        {scopeLabel(row.original)}
      </span>
    ),
  },
  { id: "status", header: "Status", accessorFn: (r) => r.status, cell: ({ row }) => <RunStatusBadge status={row.original.status} /> },
  {
    id: "duration",
    header: "Duration",
    accessorFn: (r) => r.stats.duration_seconds ?? -1,
    meta: { className: num },
    cell: ({ row }) => <span className="whitespace-nowrap">{formatDuration(row.original.stats.duration_seconds)}</span>,
  },
  {
    id: "documents",
    header: "Documents",
    accessorFn: (r) => r.stats.documents_total ?? -1,
    meta: { className: num },
    cell: ({ row }) => formatNumber(row.original.stats.documents_total),
  },
  {
    id: "issues",
    header: "Issues",
    accessorFn: (r) => r.stats.findings_total ?? -1,
    meta: { className: num },
    cell: ({ row }) => formatNumber(row.original.stats.findings_total),
  },
  {
    id: "health",
    header: "Health",
    accessorFn: (r) => r.stats.health_score ?? -1,
    meta: { className: "text-right" },
    cell: ({ row }) => <HealthBadge score={row.original.stats.health_score} />,
  },
  {
    id: "changes",
    header: "Changes",
    enableSorting: false,
    cell: ({ row }) => {
      const d = row.original.stats.diff;
      if (!d) return <span className="text-ink-3">—</span>;
      return (
        <span className="whitespace-nowrap tabular-nums">
          <span className={cn(d.opened > 0 ? "text-warning" : "text-ink-2")}>{formatNumber(d.opened)} opened</span>
          <span className="mx-1.5 text-ink-3" aria-hidden>
            ·
          </span>
          <span className={cn(d.resolved > 0 ? "text-success" : "text-ink-2")}>{formatNumber(d.resolved)} resolved</span>
        </span>
      );
    },
  },
];

export function RunsTab() {
  const navigate = useNavigate();
  const q = useAudits(100);
  const [status, setStatus] = useUrlParam("status");
  const [kind, setKind] = useUrlParam("type");
  const search = useUrlSearch("q");
  const clearParams = useClearParams();

  const all =useMemo(() => q.data ?? [], [q.data]);
  const rows = useMemo(() => {
    const needle = search.value.trim().toLowerCase();
    return all.filter((r) => {
      if (status && r.status !== status) return false;
      if (kind && r.kind !== kind) return false;
      if (!needle) return true;
      return [r.id, r.trigger, r.kind, r.scope?.tenant ?? ""].some((v) => v.toLowerCase().includes(needle));
    });
  }, [all, status, kind, search.value]);

  const filtered = !!(status || kind || search.text);
  function clear() {
    clearParams(["status", "type", "q"]);
    search.setText("");
  }

  return (
    <Card>
      <FilterBar onClear={clear} active={filtered}>
        <div className="min-w-[220px] flex-1 sm:max-w-sm">
          <span className="mb-1 block text-support text-ink-2">Search</span>
          <SearchInput value={search.text} onChange={search.setText} placeholder="Search by run id or trigger" />
        </div>
        <FilterSelect label="Status" value={status} onChange={setStatus} options={STATUS_OPTIONS} />
        <FilterSelect label="Type" value={kind} onChange={setKind} options={KIND_OPTIONS} />
      </FilterBar>
      {q.isError ? (
        <ErrorState error={q.error} onRetry={() => void q.refetch()} />
      ) : (
        <DataTable
          label="Audit runs"
          data={rows}
          columns={columns}
          loading={q.isPending}
          getRowId={(r) => r.id}
          onRowClick={(r) => navigate(links.audit(r.id))}
          initialSort={[{ id: "started", desc: true }]}
          note={all.length >= 100 ? "Showing the 100 most recent audits." : undefined}
          empty={
            filtered && all.length > 0 ? (
              <EmptyState compact icon={History} title="No audits match" description="Try a different search or clear the filters." />
            ) : (
              <EmptyState
                icon={History}
                title="No audits yet"
                description="Run your first audit to compare your source, manifest and index. Every audit is recorded here."
                action={
                  <LinkButton variant="primary" to="/reconciliation">
                    Go to Reconciliation
                  </LinkButton>
                }
              />
            )
          }
        />
      )}
    </Card>
  );
}
