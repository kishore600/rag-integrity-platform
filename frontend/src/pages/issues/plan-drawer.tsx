import type { ColumnDef } from "@tanstack/react-table";
import { useQuery } from "@tanstack/react-query";
import { CheckCircle2, Code2, PlayCircle, ShieldCheck, Trash2, XCircle } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ConfirmDialog, Drawer } from "@/components/ui/overlays";
import { DataTable } from "@/components/shared/data-table";
import { CopyButton } from "@/components/shared/copy-button";
import { LinkButton } from "@/components/shared/link-button";
import { Section, Timeline, type TimelineItem } from "@/components/shared/page";
import { EmptyState, ErrorState, Skeleton } from "@/components/shared/states";
import { PlanStatusBadge, SeverityBadge } from "@/components/shared/status";
import { useApproveCleanup, useOverview, useRepairPlan, useTriggerPlan, useVerifyPlan } from "@/hooks/queries";
import { ApiError, errorMessage, get } from "@/lib/api";
import { documentName, formatDateTime, formatNumber, formatUsd, shortHash, timeAgo } from "@/lib/format";
import { severityRank } from "@/lib/issue-meta";
import { links } from "@/lib/links";
import type { RepairItem, RepairPlan } from "@/types/api";
import { ACTION_LABEL, checkLabel, describeRepairEvent, itemStatus, itemWork } from "./labels";
import { Callout, Stat } from "./parts";

const STATUS_NOTE: Record<RepairPlan["status"], string> = {
  draft: "Nothing has been sent yet. Trigger the repair to ask your ingestion worker to re-index these documents. RAGGuard never changes your systems itself.",
  triggered: "The repair was sent to your worker. When it has finished, verify to re-check the real index.",
  partial: "Some documents are fixed and some are not. Verify again after your worker retries, or send the repair again.",
  failed: "The index still has problems for these documents. Check the results below, then send the repair again.",
  cleanup_pending: "The replacements are verified. Removing the old vectors needs your approval.",
  cleanup_triggered: "Cleanup was sent to your worker. Verify to confirm the old vectors are gone.",
  completed: "Every repair is verified. The index matches the source for each document in this plan.",
};

function ItemChecks({ item }: { item: RepairItem }) {
  const entries = Object.entries(item.checks ?? {});
  if (entries.length === 0) return <p className="mt-1 text-support text-ink-3">Not verified yet</p>;
  const sorted = [...entries].sort((a, b) => Number(a[1]) - Number(b[1]));
  return (
    <div className="mt-1.5">
      <ul className="space-y-0.5">
        {sorted.map(([k, ok]) => (
          <li key={k} className={ok ? "flex items-center gap-1.5 text-support text-ink-2" : "flex items-center gap-1.5 text-support text-critical"}>
            {ok ? <CheckCircle2 className="h-3.5 w-3.5 shrink-0 text-success" aria-label="Passed" /> : <XCircle className="h-3.5 w-3.5 shrink-0" aria-label="Failed" />}
            {checkLabel(k)}
          </li>
        ))}
      </ul>
      {item.remaining_types?.length ? <p className="mt-1 text-support text-ink-2">Still found: {item.remaining_types.map((t) => t.replace(/_/g, " ")).join(", ")}</p> : null}
    </div>
  );
}

const itemColumns: ColumnDef<RepairItem, any>[] = [ // eslint-disable-line @typescript-eslint/no-explicit-any
  {
    id: "document",
    header: "Document",
    accessorFn: (r) => documentName(r.document_id),
    meta: { className: "min-w-[200px]" },
    cell: ({ row }) => {
      const r = row.original;
      return (
        <div className="min-w-0 max-w-[240px]">
          <Link to={links.document(r.tenant_id, r.document_id)} className="block truncate font-medium text-brand hover:underline" title={r.document_id}>
            {documentName(r.document_id)}
          </Link>
          <p className="truncate text-support text-ink-2" title={r.tenant_id}>{r.tenant_id}</p>
        </div>
      );
    },
  },
  {
    id: "actions",
    header: "What will happen",
    enableSorting: false,
    meta: { className: "min-w-[200px]" },
    cell: ({ row }) => {
      const r = row.original;
      const labels = [...r.actions.map((a) => ACTION_LABEL[a] ?? a), ...(r.cleanup ? [ACTION_LABEL.cleanup_vectors] : [])];
      const work = itemWork(r);
      return (
        <div>
          <div className="flex flex-wrap gap-1.5">
            {(labels.length ? labels : [ACTION_LABEL.investigate]).map((l) => (
              <Badge key={l} tone="neutral">{l}</Badge>
            ))}
          </div>
          {work.length ? <p className="mt-1 text-support tabular-nums text-ink-2">{work.join(" · ")}</p> : null}
        </div>
      );
    },
  },
  {
    id: "severity",
    header: "Severity",
    accessorFn: (r) => severityRank[r.worst_severity],
    meta: { className: "w-[110px]" },
    cell: ({ row }) => <SeverityBadge severity={row.original.worst_severity} />,
  },
  {
    id: "status",
    header: "Status",
    accessorFn: (r) => r.status,
    meta: { className: "min-w-[190px]" },
    cell: ({ row }) => {
      const s = itemStatus(row.original.status);
      return (
        <div>
          <Badge tone={s.tone} dot>{s.label}</Badge>
          <ItemChecks item={row.original} />
        </div>
      );
    },
  },
];

function PlanSkeleton() {
  return (
    <div className="space-y-5 px-5 py-4" aria-busy aria-label="Loading repair plan">
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-3">
        {Array.from({ length: 6 }).map((_, i) => (
          <Skeleton key={i} className="h-12" />
        ))}
      </div>
      <Skeleton className="h-16 w-full" />
      <Skeleton className="h-48 w-full" />
    </div>
  );
}

export function PlanDrawer({ id, onClose }: { id: string; onClose: () => void }) {
  const query = useRepairPlan(id);
  const overview = useOverview();
  const trigger = useTriggerPlan();
  const verify = useVerifyPlan();
  const approve = useApproveCleanup();
  const [approveOpen, setApproveOpen] = useState(false);
  const [webhookMissing, setWebhookMissing] = useState<string | null>(null);
  const [showPayload, setShowPayload] = useState(false);

  const payload = useQuery({
    queryKey: ["repair-payload", id],
    queryFn: () => get<object>(`/api/repairs/${encodeURIComponent(id)}/payload`),
    enabled: showPayload,
    retry: false,
    staleTime: 0,
    gcTime: 0,
  });

  const plan = query.data;
  const notFound = query.error instanceof ApiError && query.error.status === 404;
  const webhookKnownMissing = !!overview.data && !overview.data.demo && !overview.data.repair_webhook_configured;

  async function doTrigger() {
    setWebhookMissing(null);
    try {
      const p = await trigger.mutateAsync(id);
      const n = p.items.filter((i) => i.actions.length > 0).length;
      toast.success("Repair sent to your worker", { description: `${formatNumber(n)} document${n === 1 ? "" : "s"} to reprocess. Verify once your worker has finished.` });
    } catch (err) {
      const message = errorMessage(err);
      if (/no repair webhook configured/i.test(message)) setWebhookMissing(message);
      toast.error("Couldn't send the repair", { description: message });
    }
  }

  async function doVerify() {
    try {
      const p = await verify.mutateAsync(id);
      if (p.status === "completed") toast.success("Verified", { description: "Every repair is in place." });
      else if (p.status === "cleanup_pending") toast.success("Replacements verified", { description: "The old vectors are waiting for your approval." });
      else toast.warning("Verified: not everything is fixed yet", { description: "Some documents still have issues. See the results in the plan." });
    } catch (err) {
      toast.error("Couldn't verify the plan", { description: errorMessage(err) });
    }
  }

  async function doApprove() {
    const p = await approve.mutateAsync(id);
    toast.success("Cleanup sent to your worker", { description: `${formatNumber(p.summary.vectors_to_remove)} old vectors will be removed. Verify to confirm.` });
  }

  const status = plan?.status;
  const canTrigger = status === "draft";
  const canRetry = status === "partial" || status === "failed";
  const canVerify = status === "triggered" || status === "partial" || status === "failed" || status === "cleanup_triggered";
  const canApprove = status === "cleanup_pending";

  const events: TimelineItem[] = [...(plan?.events ?? [])].reverse().map((e) => {
    const d = describeRepairEvent(e);
    return { id: e.id, title: d.title, tone: d.tone, body: d.body, meta: formatDateTime(e.ts) };
  });

  const s = plan?.summary;

  return (
    <>
      <Drawer
        open
        onOpenChange={(o) => {
          if (!o) onClose();
        }}
        width="xl"
        title={plan ? `Repair plan ${shortHash(plan.id, 8)}` : notFound ? "Repair plan not found" : query.isError ? "Couldn't load this plan" : "Loading repair plan"}
        description={
          plan ? (
            <span className="flex flex-wrap items-center gap-2">
              <PlanStatusBadge status={plan.status} />
              <span title={formatDateTime(plan.created_at)}>Created {timeAgo(plan.created_at)}</span>
            </span>
          ) : undefined
        }
        footer={
          plan ? (
            <>
              <Button variant="secondary" onClick={() => setShowPayload((v) => !v)} className="mr-auto">
                <Code2 className="h-4 w-4" aria-hidden /> {showPayload ? "Hide payload" : "View payload"}
              </Button>
              {canRetry ? (
                <Button variant="secondary" onClick={doTrigger} loading={trigger.isPending}>Send repair again</Button>
              ) : null}
              {canTrigger ? (
                <Button variant="primary" onClick={doTrigger} loading={trigger.isPending}>
                  <PlayCircle className="h-4 w-4" aria-hidden /> Trigger repair
                </Button>
              ) : null}
              {canVerify ? (
                <Button variant="primary" onClick={doVerify} loading={verify.isPending}>
                  <ShieldCheck className="h-4 w-4" aria-hidden /> Verify now
                </Button>
              ) : null}
              {canApprove ? (
                <Button variant="danger" onClick={() => setApproveOpen(true)}>
                  <Trash2 className="h-4 w-4" aria-hidden /> Approve cleanup
                </Button>
              ) : null}
            </>
          ) : undefined
        }
      >
        {query.isPending ? (
          <PlanSkeleton />
        ) : notFound ? (
          <EmptyState title="Repair plan not found" description="It may belong to another workspace. Go back to the list to pick another." action={<Button variant="secondary" onClick={onClose}>Back to plans</Button>} />
        ) : query.isError ? (
          <ErrorState error={query.error} onRetry={() => void query.refetch()} compact />
        ) : plan && s ? (
          <div className="divide-y divide-line">
            <Section title="Summary">
              <div className="grid grid-cols-2 gap-x-4 gap-y-4 sm:grid-cols-3">
                <Stat label="Documents affected" value={formatNumber(s.documents_affected)} />
                <Stat label="Chunks to regenerate" value={formatNumber(s.chunks_to_regenerate)} />
                <Stat label="Estimated tokens" value={formatNumber(s.estimated_tokens)} />
                <Stat label="Estimated cost" value={formatUsd(s.estimated_cost_usd)} />
                <Stat label="Vectors to remove" value={formatNumber(s.vectors_to_remove)} />
                {s.savings_vs_full_reindex_pct !== null ? <Stat label="Savings vs full reindex" value={`${s.savings_vs_full_reindex_pct}%`} /> : null}
              </div>
            </Section>

            <Section title="Where this stands">
              <Callout tone={plan.status === "completed" ? "success" : "neutral"} role="status">
                {STATUS_NOTE[plan.status]}
              </Callout>
              {canTrigger && webhookKnownMissing && !webhookMissing ? (
                <div className="mt-3">
                  <Callout tone="warning">
                    No repair webhook is set up yet, so triggering will fail. You can still copy the payload and hand it to your worker yourself.
                    <span className="mt-2 block">
                      <LinkButton variant="secondary" size="sm" to="/integrations">Set up the repair webhook</LinkButton>
                    </span>
                  </Callout>
                </div>
              ) : null}
              {webhookMissing ? (
                <div className="mt-3">
                  <Callout tone="critical" role="alert">
                    {webhookMissing}
                    <span className="mt-2 block">
                      <LinkButton variant="secondary" size="sm" to="/integrations">Set up the repair webhook</LinkButton>
                    </span>
                  </Callout>
                </div>
              ) : null}
            </Section>

            {showPayload ? (
              <Section title="Payload" description="The signed request RAGGuard sends to your worker for the repair step." actions={payload.data ? <CopyButton text={JSON.stringify(payload.data, null, 2)} label="Copy JSON" /> : undefined}>
                {payload.isFetching ? (
                  <Skeleton className="h-40 w-full" />
                ) : payload.isError ? (
                  <ErrorState error={payload.error} onRetry={() => void payload.refetch()} compact />
                ) : payload.data ? (
                  <pre className="max-h-96 overflow-auto rounded-control border border-line bg-surface p-3 text-support text-ink">{JSON.stringify(payload.data, null, 2)}</pre>
                ) : null}
              </Section>
            ) : null}

            <Section title={`Documents (${formatNumber(plan.items.length)})`}>
              <div className="-mx-5 border-y border-line">
                <DataTable label="Plan documents" data={plan.items} columns={itemColumns} pageSize={10} getRowId={(r) => `${r.tenant_id}/${r.document_id}`} initialSort={[{ id: "severity", desc: true }]} empty={<EmptyState compact title="No documents in this plan" />} />
              </div>
            </Section>

            <Section title="History">
              {events.length > 0 ? <Timeline items={events} /> : <p className="text-body text-ink-2">Nothing has happened to this plan yet.</p>}
            </Section>
          </div>
        ) : null}
      </Drawer>

      {plan ? (
        <ConfirmDialog
          open={approveOpen}
          onOpenChange={setApproveOpen}
          destructive
          title={`Remove ${formatNumber(plan.summary.vectors_to_remove)} old vectors?`}
          description="This cannot be undone."
          confirmLabel={`Remove ${formatNumber(plan.summary.vectors_to_remove)} vectors`}
          onConfirm={doApprove}
        >
          <div className="space-y-2 text-body text-ink">
            <p>
              RAGGuard will ask your worker to delete <span className="font-semibold tabular-nums">{formatNumber(plan.summary.vectors_to_remove)}</span> superseded vector{plan.summary.vectors_to_remove === 1 ? "" : "s"} from your index. Deleted vectors cannot be restored.
            </p>
            <p className="text-ink-2">The replacements for these documents were already verified. The exact list is read from your live index again when you confirm, so it reflects the index as it is right now.</p>
          </div>
        </ConfirmDialog>
      ) : null}
    </>
  );
}
