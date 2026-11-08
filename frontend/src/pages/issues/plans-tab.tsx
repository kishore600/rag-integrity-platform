import type { ColumnDef } from "@tanstack/react-table";
import { ClipboardList, Wrench } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Label, Select } from "@/components/ui/form";
import { DataTable } from "@/components/shared/data-table";
import { EmptyState, ErrorState, Skeleton } from "@/components/shared/states";
import { PlanStatusBadge } from "@/components/shared/status";
import { useCreatePlan, useRecommendations, useRepairs } from "@/hooks/queries";
import { errorMessage } from "@/lib/api";
import { formatDateTime, formatNumber, formatUsd, shortHash, timeAgo } from "@/lib/format";
import { SEVERITIES } from "@/lib/issue-meta";
import type { PlanRequest, Recommendations, RepairPlan, WorkloadSummary } from "@/types/api";
import { PlanDrawer } from "./plan-drawer";
import { Stat } from "./parts";
import { oneOf, useParamState } from "./url-state";

const MIN_OPTIONS = ["", ...SEVERITIES] as const;

const planColumns: ColumnDef<RepairPlan, any>[] = [ // eslint-disable-line @typescript-eslint/no-explicit-any
  {
    id: "plan",
    header: "Plan",
    accessorFn: (r) => r.id,
    meta: { className: "w-[150px]" },
    cell: ({ row }) => <span className="font-mono text-support text-ink" title={row.original.id}>{shortHash(row.original.id, 8)}</span>,
  },
  { id: "status", header: "Status", accessorFn: (r) => r.status, meta: { className: "w-[170px]" }, cell: ({ row }) => <PlanStatusBadge status={row.original.status} /> },
  {
    id: "created",
    header: "Created",
    accessorFn: (r) => r.created_at,
    meta: { className: "w-[130px] whitespace-nowrap" },
    cell: ({ row }) => <span className="text-ink-2" title={formatDateTime(row.original.created_at)}>{timeAgo(row.original.created_at)}</span>,
  },
  { id: "documents", header: "Documents", accessorFn: (r) => r.summary.documents_affected, meta: { className: "w-[110px] text-right tabular-nums" }, cell: ({ row }) => formatNumber(row.original.summary.documents_affected) },
  { id: "chunks", header: "Chunks", accessorFn: (r) => r.summary.chunks_to_regenerate, meta: { className: "w-[110px] text-right tabular-nums" }, cell: ({ row }) => formatNumber(row.original.summary.chunks_to_regenerate) },
  { id: "cost", header: "Est. cost", accessorFn: (r) => r.summary.estimated_cost_usd, meta: { className: "w-[110px] text-right tabular-nums" }, cell: ({ row }) => formatUsd(row.original.summary.estimated_cost_usd) },
];

function RecommendationStats({ s }: { s: WorkloadSummary }) {
  return (
    <div className="grid grid-cols-2 gap-x-4 gap-y-5 sm:grid-cols-3 xl:grid-cols-6">
      <Stat label="Documents to reprocess" value={formatNumber(s.documents_to_reprocess)} />
      <Stat label="Chunks to regenerate" value={formatNumber(s.chunks_to_regenerate)} />
      <Stat label="Estimated tokens" value={formatNumber(s.estimated_tokens)} />
      <Stat label="Estimated cost" value={formatUsd(s.estimated_cost_usd)} />
      {s.savings_vs_full_reindex_pct !== null ? <Stat label="Savings vs full reindex" value={`${s.savings_vs_full_reindex_pct}%`} /> : null}
      <Stat label="Vectors to remove" value={formatNumber(s.vectors_to_remove)} />
    </div>
  );
}

function Recommended({ data, min }: { data: Recommendations; min: string }) {
  const s = data.summary;
  if (s.documents_affected === 0) {
    return (
      <EmptyState
        compact
        icon={Wrench}
        title="Nothing to repair"
        description={min ? `No open document issues at ${min} severity or above. Choose a lower minimum to see more.` : "No open issues need a repair. New findings show up here after the next audit."}
      />
    );
  }
  return (
    <div className="space-y-5">
      <p className="text-body text-ink">
        <span className="font-semibold tabular-nums">{formatNumber(s.documents_affected)}</span> document{s.documents_affected === 1 ? "" : "s"} with open issues, across{" "}
        <span className="tabular-nums">{formatNumber(s.tenants_affected.length)}</span> tenant{s.tenants_affected.length === 1 ? "" : "s"}.
      </p>
      <RecommendationStats s={s} />
      <p className="text-support text-ink-2">{s.assumptions}</p>
      {data.items_truncated ? <p className="text-support text-ink-2">The preview covers the most severe 200 documents. A plan includes every matching document.</p> : null}
    </div>
  );
}

export function PlansTab() {
  const { params, set } = useParamState();
  const min = oneOf(params.get("min"), MIN_OPTIONS, "");
  const activePlan = params.get("plan");
  const recs = useRecommendations(min || undefined);
  const plans = useRepairs();
  const createPlan = useCreatePlan();

  async function createFromRecommendations() {
    const req: PlanRequest = min ? { min_severity: min } : {};
    try {
      const plan = await createPlan.mutateAsync(req);
      toast.success("Repair plan created", { description: `${formatNumber(plan.summary.documents_affected)} document${plan.summary.documents_affected === 1 ? "" : "s"} to repair. Review it, then trigger the repair.` });
      set({ plan: plan.id }, { replace: false });
    } catch (err) {
      toast.error("Couldn't create the repair plan", { description: errorMessage(err) });
    }
  }

  const severityControl = (
    <div className="w-full sm:w-52">
      <Label htmlFor="min-severity">Minimum severity</Label>
      <Select id="min-severity" value={min} onChange={(e) => set({ min: e.target.value || null })}>
        <option value="">All severities</option>
        {SEVERITIES.map((s) => (
          <option key={s} value={s}>{`${s.charAt(0).toUpperCase()}${s.slice(1)} and above`}</option>
        ))}
      </Select>
    </div>
  );

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader title="Recommended work" description="The smallest safe set of repairs for your open issues, and what it costs compared with re-embedding everything." />
        <CardBody>
          {recs.isPending ? (
            <Skeleton className="h-28 w-full" />
          ) : recs.isError ? (
            <ErrorState error={recs.error} onRetry={() => void recs.refetch()} compact />
          ) : (
            <Recommended data={recs.data} min={min} />
          )}
          <div className="mt-5 flex flex-wrap items-end gap-3 border-t border-line pt-4">
            {severityControl}
            <Button
              variant="primary"
              onClick={createFromRecommendations}
              loading={createPlan.isPending}
              disabled={!recs.data || recs.data.summary.documents_affected === 0}
              title={recs.data && recs.data.summary.documents_affected === 0 ? "There is nothing to repair" : undefined}
            >
              Create plan from recommendations
            </Button>
          </div>
        </CardBody>
      </Card>

      <Card>
        <CardHeader title="Repair plans" description="Each plan is sent to your worker, then verified against your real index." />
        {plans.isError && !plans.data ? (
          <ErrorState error={plans.error} onRetry={() => void plans.refetch()} />
        ) : (
          <DataTable
            label="Repair plans"
            data={plans.data ?? []}
            columns={planColumns}
            loading={plans.isPending}
            getRowId={(r) => r.id}
            activeRowId={activePlan}
            onRowClick={(r) => set({ plan: r.id }, { replace: false })}
            initialSort={[{ id: "created", desc: true }]}
            empty={<EmptyState icon={ClipboardList} title="No repair plans yet" description="Create one from the recommendations above, or select issues in the Issues tab and create a plan from them." />}
          />
        )}
      </Card>

      {activePlan ? <PlanDrawer key={activePlan} id={activePlan} onClose={() => set({ plan: null }, { replace: false })} /> : null}
    </div>
  );
}
