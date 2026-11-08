import type { ColumnDef } from "@tanstack/react-table";
import { PlayCircle, ShieldCheck, SearchX } from "lucide-react";
import { useMemo, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Checkbox, SearchInput } from "@/components/ui/form";
import { DataTable } from "@/components/shared/data-table";
import { FilterBar, FilterSelect } from "@/components/shared/filters";
import { EmptyState, ErrorState, Skeleton } from "@/components/shared/states";
import { IssueStatusBadge, SeverityBadge } from "@/components/shared/status";
import { useCreatePlan, useIgnoreIssue, useIssues, useOverview, type IssueFilters } from "@/hooks/queries";
import { useRunAudit } from "@/hooks/use-run-audit";
import { errorMessage } from "@/lib/api";
import { cn } from "@/lib/cn";
import { documentName, formatNumber, timeAgo, formatDateTime } from "@/lib/format";
import { ISSUE_TYPES, SEVERITIES, issueLabel, severityRank } from "@/lib/issue-meta";
import { links } from "@/lib/links";
import type { Issue, Severity } from "@/types/api";
import { IgnoreDialog } from "./parts";
import { oneOf, useDebouncedParam, useParamState } from "./url-state";

const STATUSES = ["open", "resolved", "ignored", "all"] as const;
const STATUS_OPTIONS = [
  { value: "open", label: "Open" },
  { value: "resolved", label: "Resolved" },
  { value: "ignored", label: "Ignored" },
  { value: "all", label: "All statuses" },
];
const SEVERITY_DOT: Record<Severity, string> = { critical: "bg-critical", high: "bg-warning", medium: "bg-info", low: "bg-ink-3", info: "bg-ink-3" };
const LIMIT = 500;

/** Open issues by severity. Clicking one filters the table to it; clicking it again clears the filter. */
function SeverityChips({ active, onPick }: { active: string; onPick: (s: string) => void }) {
  const overview = useOverview();
  if (overview.isPending) {
    return (
      <div className="flex flex-wrap gap-2" aria-hidden>
        {SEVERITIES.map((s) => (
          <Skeleton key={s} className="h-8 w-24 rounded-full" />
        ))}
      </div>
    );
  }
  if (!overview.data) return null;
  const counts = overview.data.issues.by_severity;
  return (
    <div className="flex flex-wrap items-center gap-2" role="group" aria-label="Filter open issues by severity">
      <span className="mr-1 text-support text-ink-2">Open issues</span>
      {SEVERITIES.map((s) => {
        const on = active === s;
        return (
          <button
            key={s}
            type="button"
            aria-pressed={on}
            onClick={() => onPick(on ? "" : s)}
            className={cn(
              "inline-flex h-8 items-center gap-2 rounded-full border px-3 text-support transition-colors",
              on ? "border-brand bg-brand-light text-brand" : "border-line bg-workspace text-ink-2 hover:border-line-strong hover:bg-surface hover:text-ink",
            )}
          >
            <span className={cn("h-1.5 w-1.5 rounded-full", SEVERITY_DOT[s])} aria-hidden />
            <span className="capitalize">{s}</span>
            <span className="font-semibold tabular-nums text-ink">{formatNumber(counts?.[s] ?? 0)}</span>
          </button>
        );
      })}
    </div>
  );
}

export function IssuesTab({ activeIssueId }: { activeIssueId?: string }) {
  const navigate = useNavigate();
  const location = useLocation();
  const { params, set } = useParamState();
  const overview = useOverview();
  const audit = useRunAudit();
  const search = useDebouncedParam("q");

  const status = oneOf(params.get("status"), STATUSES, "open");
  const severity = oneOf(params.get("severity"), ["", ...SEVERITIES] as const, "");
  const type = oneOf(params.get("type"), ["", ...ISSUE_TYPES] as const, "");
  const tenant = params.get("tenant") ?? "";
  const q = search.value;

  const filters: IssueFilters = { status, severity: severity || undefined, type: type || undefined, tenant: tenant || undefined, q: q || undefined, limit: LIMIT };
  const issues = useIssues(filters);
  const items = useMemo(() => issues.data?.items ?? [], [issues.data]);
  const total = issues.data?.total ?? 0;

  const createPlan = useCreatePlan();
  const ignore = useIgnoreIssue();
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [ignoreOpen, setIgnoreOpen] = useState(false);
  // The issues the dialog was opened for. Fixed at that moment so the count does not shrink while they are being ignored.
  const [ignoreTargets, setIgnoreTargets] = useState<Issue[]>([]);

  // Only rows that are still on screen count as selected, so a filter change can never act on hidden rows.
  const selectedItems = useMemo(() => items.filter((i) => selected.has(i.id)), [items, selected]);
  const plannable = selectedItems.filter((i) => i.status === "open" && i.document_id !== "*");
  const ignorable = selectedItems.filter((i) => i.status !== "ignored");

  const tenantOptions = useMemo(() => {
    const ids = new Set((overview.data?.documents.tenants ?? []).map((t) => t.tenant_id));
    if (tenant) ids.add(tenant);
    return [{ value: "", label: "All tenants" }, ...[...ids].sort().map((id) => ({ value: id, label: id }))];
  }, [overview.data, tenant]);

  const hasFilters = !!(q || severity || type || tenant || status !== "open");
  const clearFilters = () => {
    search.setInput("");
    set({ q: null, status: null, severity: null, type: null, tenant: null });
  };
  const noAuditYet = !!overview.data && overview.data.latest_run === null;

  const allSelected = items.length > 0 && selectedItems.length === items.length;
  const someSelected = selectedItems.length > 0 && !allSelected;

  const toggle = (id: string) =>
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  const columns = useMemo<ColumnDef<Issue, any>[]>( // eslint-disable-line @typescript-eslint/no-explicit-any
    () => [
      {
        id: "select",
        enableSorting: false,
        meta: { className: "w-10 pr-0" },
        header: () => (
          <Checkbox
            aria-label={`Select all ${items.length} issues`}
            checked={allSelected}
            ref={(el) => {
              if (el) el.indeterminate = someSelected;
            }}
            onChange={() => setSelected(allSelected ? new Set() : new Set(items.map((i) => i.id)))}
          />
        ),
        cell: ({ row }) => (
          <div onClick={(e) => e.stopPropagation()} onKeyDown={(e) => e.stopPropagation()}>
            <Checkbox aria-label={`Select issue: ${row.original.title}`} checked={selected.has(row.original.id)} onChange={() => toggle(row.original.id)} />
          </div>
        ),
      },
      {
        id: "severity",
        header: "Severity",
        accessorFn: (r) => severityRank[r.severity],
        meta: { className: "w-[120px]" },
        cell: ({ row }) => <SeverityBadge severity={row.original.severity} />,
      },
      {
        id: "issue",
        header: "Issue",
        accessorFn: (r) => r.title,
        meta: { className: "min-w-[240px]" },
        cell: ({ row }) => (
          <div className="min-w-0 max-w-[420px]">
            <p className="truncate font-medium text-ink" title={row.original.title}>{row.original.title}</p>
            <p className="truncate text-support text-ink-2">{issueLabel(row.original.type)}</p>
          </div>
        ),
      },
      {
        id: "document",
        header: "Document",
        accessorFn: (r) => documentName(r.document_id),
        meta: { className: "min-w-[180px]" },
        cell: ({ row }) => {
          const r = row.original;
          return (
            <div className="min-w-0 max-w-[260px]">
              <p className="truncate text-ink" title={r.document_id}>{r.document_id === "*" ? "Whole collection" : documentName(r.document_id)}</p>
              <p className="truncate text-support text-ink-2" title={r.tenant_id}>{r.tenant_id}</p>
            </div>
          );
        },
      },
      { id: "status", header: "Status", accessorFn: (r) => r.status, meta: { className: "w-[110px]" }, cell: ({ row }) => <IssueStatusBadge status={row.original.status} /> },
      {
        id: "first_seen",
        header: "First seen",
        accessorFn: (r) => r.first_seen_at,
        meta: { className: "w-[110px] whitespace-nowrap" },
        cell: ({ row }) => <span className="text-ink-2" title={formatDateTime(row.original.first_seen_at)}>{timeAgo(row.original.first_seen_at)}</span>,
      },
      {
        id: "last_seen",
        header: "Last seen",
        accessorFn: (r) => r.last_seen_at,
        meta: { className: "w-[110px] whitespace-nowrap" },
        cell: ({ row }) => <span className="text-ink-2" title={formatDateTime(row.original.last_seen_at)}>{timeAgo(row.original.last_seen_at)}</span>,
      },
      {
        id: "seen",
        header: "Seen",
        accessorFn: (r) => r.occurrences,
        meta: { className: "w-[70px] text-right tabular-nums" },
        cell: ({ row }) => <span className="tabular-nums text-ink-2" title={`Seen in ${row.original.occurrences} audit${row.original.occurrences === 1 ? "" : "s"}`}>{formatNumber(row.original.occurrences)}</span>,
      },
    ],
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [items, selected, allSelected, someSelected],
  );

  async function createPlanFromSelection() {
    try {
      const plan = await createPlan.mutateAsync({ issue_ids: plannable.map((i) => i.id) });
      toast.success("Repair plan created", { description: `${formatNumber(plan.summary.documents_affected)} document${plan.summary.documents_affected === 1 ? "" : "s"} to repair.` });
      setSelected(new Set());
      set({ view: "plans", plan: plan.id }, { replace: false });
    } catch (err) {
      toast.error("Couldn't create the repair plan", { description: errorMessage(err) });
    }
  }

  async function ignoreSelection(reason: string) {
    const targets = ignoreTargets;
    let done = 0;
    for (const i of targets) {
      try {
        await ignore.mutateAsync({ id: i.id, reason: reason || undefined });
        done++;
      } catch (err) {
        throw new Error(`Ignored ${done} of ${targets.length} before an error: ${errorMessage(err)}`);
      }
    }
    toast.success(`Ignored ${done} issue${done === 1 ? "" : "s"}`);
    setSelected(new Set());
  }

  const empty = hasFilters ? (
    <EmptyState
      icon={SearchX}
      title="No issues match these filters"
      description="Try a different search, or remove a filter to see more."
      action={<Button variant="secondary" onClick={clearFilters}>Clear filters</Button>}
    />
  ) : noAuditYet ? (
    <EmptyState
      icon={PlayCircle}
      title="No audit has run yet"
      description="Run your first audit to compare your source, manifest and index. Any differences show up here."
      action={
        <Button variant="primary" onClick={() => audit.run()} loading={audit.running} disabled={!!audit.disabledReason && !audit.running} title={audit.disabledReason ?? undefined}>
          Run audit
        </Button>
      }
    />
  ) : (
    <EmptyState icon={ShieldCheck} title="No open issues" description="Your index matches your source. New findings appear here after each audit." />
  );

  return (
    <div className="space-y-4">
      <SeverityChips active={severity} onPick={(s) => set({ severity: s || null })} />

      <Card>
        <FilterBar onClear={clearFilters} active={hasFilters}>
          <label className="block min-w-[220px] flex-1 sm:max-w-sm">
            <span className="mb-1 block text-support text-ink-2">Search</span>
            <SearchInput value={search.input} onChange={search.setInput} placeholder="Search by document or title" />
          </label>
          <FilterSelect label="Status" value={status} onChange={(v) => set({ status: v === "open" ? null : v })} options={STATUS_OPTIONS} />
          <FilterSelect label="Severity" value={severity} onChange={(v) => set({ severity: v || null })} options={[{ value: "", label: "All severities" }, ...SEVERITIES.map((s) => ({ value: s, label: s.charAt(0).toUpperCase() + s.slice(1) }))]} />
          <FilterSelect label="Type" value={type} onChange={(v) => set({ type: v || null })} options={[{ value: "", label: "All types" }, ...ISSUE_TYPES.map((t) => ({ value: t, label: issueLabel(t) }))]} className="min-w-[180px]" />
          <FilterSelect label="Tenant" value={tenant} onChange={(v) => set({ tenant: v || null })} options={tenantOptions} />
        </FilterBar>

        {selectedItems.length > 0 ? (
          <div className="flex flex-wrap items-center gap-2 border-b border-line bg-brand-light/50 px-4 py-2.5" role="region" aria-label="Bulk actions">
            <span className="mr-1 text-body font-medium text-ink tabular-nums">{selectedItems.length} selected:</span>
            <Button
              size="sm"
              variant="primary"
              onClick={createPlanFromSelection}
              loading={createPlan.isPending}
              disabled={plannable.length === 0}
              title={plannable.length === 0 ? "Only open issues on a specific document can be repaired" : undefined}
            >
              Create repair plan
            </Button>
            <Button
              size="sm"
              variant="secondary"
              onClick={() => {
                setIgnoreTargets(ignorable);
                setIgnoreOpen(true);
              }}
              disabled={ignorable.length === 0}
              title={ignorable.length === 0 ? "These issues are already ignored" : undefined}
            >
              Ignore
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setSelected(new Set())}>Clear selection</Button>
          </div>
        ) : null}

        {issues.isError && !issues.data ? (
          <ErrorState error={issues.error} onRetry={() => void issues.refetch()} />
        ) : (
          <div className={cn("transition-opacity", issues.isPlaceholderData && "opacity-60")} aria-busy={issues.isFetching}>
            <DataTable
              label="Integrity issues"
              data={items}
              columns={columns}
              loading={issues.isPending}
              getRowId={(r) => r.id}
              activeRowId={activeIssueId ?? null}
              onRowClick={(r) => navigate({ pathname: links.issue(r.id), search: location.search })}
              initialSort={[{ id: "severity", desc: true }]}
              empty={empty}
              note={total > items.length ? `Showing the first ${formatNumber(LIMIT)} of ${formatNumber(total)}. Narrow the filters.` : undefined}
            />
          </div>
        )}
      </Card>

      <IgnoreDialog open={ignoreOpen} onOpenChange={setIgnoreOpen} count={ignoreTargets.length} onConfirm={ignoreSelection} />
    </div>
  );
}
