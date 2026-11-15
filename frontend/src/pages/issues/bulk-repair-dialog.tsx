import { Wrench } from "lucide-react";
import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Field, Input, Select, Switch, Textarea } from "@/components/ui/form";
import { Modal } from "@/components/ui/overlays";
import { Skeleton } from "@/components/shared/states";
import { useBulkRepair, useOverview, usePreviewRepair } from "@/hooks/queries";
import { ApiError, errorMessage } from "@/lib/api";
import { formatNumber, formatUsd } from "@/lib/format";
import { SEVERITIES } from "@/lib/issue-meta";
import type { Severity } from "@/types/api";
import { Callout, Stat } from "./parts";

const MIN_SEVERITY = [
  { value: "", label: "All severities" },
  { value: "high", label: "High and critical" },
  { value: "critical", label: "Critical only" },
] as const;

/**
 * Repair everything that matches in one go: one plan for many documents, so nobody has to tick them one by one. It shows what
 * will happen first, can send the plan to the repair worker in the same step, and can email it to the people who will fix it.
 * Removing old vectors always stays a separate approval.
 */
export function BulkRepairDialog({ open, onOpenChange, onCreated }: { open: boolean; onOpenChange: (open: boolean) => void; onCreated: (planId: string) => void }) {
  const overview = useOverview();
  const [minSeverity, setMinSeverity] = useState<"" | Severity>("");
  const [tenant, setTenant] = useState("");
  const [send, setSend] = useState<boolean | null>(null); // null: follow the default (on when a worker is set up)
  const [emailOn, setEmailOn] = useState(false);
  const [emailTo, setEmailTo] = useState("");
  const [note, setNote] = useState("");
  const [error, setError] = useState<string | null>(null);

  const filters = { min_severity: minSeverity || undefined, tenant: tenant || undefined };
  const preview = usePreviewRepair(filters, open);
  const bulk = useBulkRepair();
  const p = preview.data;
  const noMatch = preview.error instanceof ApiError && preview.error.status === 404;
  const sendOn = !!p?.webhook_configured && (send ?? true) && p.to_reprocess > 0;
  const emailReady = !!p?.email_configured;

  const tenants = useMemo(() => [...new Set((overview.data?.documents.tenants ?? []).map((t) => t.tenant_id))].sort(), [overview.data]);

  async function run() {
    setError(null);
    try {
      const r = await bulk.mutateAsync({ ...filters, send: sendOn, email_to: emailOn && emailReady ? emailTo : undefined, note: emailOn && note.trim() ? note.trim() : undefined });
      const n = r.plan.items.length;
      const docs = `${formatNumber(n)} document${n === 1 ? "" : "s"}`;
      toast.success(r.sent ? "Repair sent to your worker" : "Repair plan created", {
        description: [docs, r.sent ? "sent in one request" : "not sent yet", r.emailed ? `emailed to ${r.emailed.length} ${r.emailed.length === 1 ? "person" : "people"}` : null].filter(Boolean).join(", ") + ".",
      });
      for (const problem of r.problems) {
        toast.warning(problem.step === "email" ? "The plan was created, but the email was not sent" : "The plan was created, but it was not sent to your worker", { description: problem.message });
      }
      onOpenChange(false);
      onCreated(r.plan.id);
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  const confirm = bulk.isPending ? "Working…" : sendOn ? "Create and send" : "Create plan";

  return (
    <Modal
      open={open}
      onOpenChange={(o) => {
        if (!bulk.isPending) {
          setError(null);
          onOpenChange(o);
        }
      }}
      title="Repair all open issues"
      description="One plan for every matching document, instead of ticking them one by one."
      size="md"
      footer={
        <>
          <Button variant="secondary" onClick={() => onOpenChange(false)} disabled={bulk.isPending}>Cancel</Button>
          <Button variant="primary" onClick={run} loading={bulk.isPending} disabled={!p || noMatch || (emailOn && !emailTo.trim())}>
            <Wrench className="h-4 w-4" aria-hidden /> {confirm}
          </Button>
        </>
      }
    >
      <div className="space-y-5">
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Which issues">
            {(f) => (
              <Select {...f} value={minSeverity} onChange={(e) => setMinSeverity(e.target.value as "" | Severity)}>
                {MIN_SEVERITY.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
              </Select>
            )}
          </Field>
          <Field label="Which customer (tenant)">
            {(f) => (
              <Select {...f} value={tenant} onChange={(e) => setTenant(e.target.value)}>
                <option value="">All tenants</option>
                {tenants.map((t) => <option key={t} value={t}>{t}</option>)}
              </Select>
            )}
          </Field>
        </div>

        {preview.isPending ? (
          <Skeleton className="h-24 w-full" />
        ) : noMatch ? (
          <Callout tone="neutral" role="status">No open issue on a specific document matches that choice. Pick a wider selection.</Callout>
        ) : preview.isError ? (
          <Callout tone="critical" role="alert">{errorMessage(preview.error)}</Callout>
        ) : p ? (
          <div className="rounded-card border border-line bg-app p-4">
            <div className="grid grid-cols-2 gap-x-4 gap-y-3 sm:grid-cols-3">
              <Stat label="Documents" value={formatNumber(p.documents)} hint={`${formatNumber(p.issues)} issue${p.issues === 1 ? "" : "s"}`} />
              <Stat label="To re-process" value={formatNumber(p.to_reprocess)} hint={`${formatNumber(p.summary.chunks_to_regenerate)} chunks`} />
              <Stat label="Estimated cost" value={formatUsd(p.summary.estimated_cost_usd)} />
              <Stat label="Vectors to remove" value={formatNumber(p.summary.vectors_to_remove)} hint={p.cleanup_only || p.summary.vectors_to_remove ? "needs your approval later" : undefined} />
              {SEVERITIES.filter((s) => p.by_severity[s]).map((s) => <Stat key={s} label={`${s.charAt(0).toUpperCase()}${s.slice(1)}`} value={formatNumber(p.by_severity[s])} />)}
            </div>
          </div>
        ) : null}

        {p ? (
          <div className="space-y-4">
            <div className="flex items-start justify-between gap-4">
              <div>
                <p className="text-card text-ink">Send it to my repair worker now</p>
                <p className="mt-0.5 text-support text-ink-2">
                  {!p.webhook_configured ? (
                    <>No repair worker is set up, so the plan is only created. Set one up under <Link to="/integrations" className="text-brand hover:underline">Integrations</Link>.</>
                  ) : p.to_reprocess === 0 ? (
                    "Nothing here needs re-processing; these documents only need old vectors removed, which you approve afterwards."
                  ) : (
                    "One signed request carries every document. Removing old vectors still waits for your approval."
                  )}
                </p>
              </div>
              <Switch checked={sendOn} onChange={setSend} label="Send it to my repair worker now" disabled={!p.webhook_configured || p.to_reprocess === 0} />
            </div>

            <div className="flex items-start justify-between gap-4">
              <div>
                <p className="text-card text-ink">Also email the plan</p>
                <p className="mt-0.5 text-support text-ink-2">
                  {emailReady ? (
                    "A readable summary and table, a CSV that opens in Excel, and the exact JSON your worker receives."
                  ) : (
                    <>Email is not set up. Add your mail server under <Link to="/integrations" className="text-brand hover:underline">Integrations</Link> first.</>
                  )}
                </p>
              </div>
              <Switch checked={emailOn && emailReady} onChange={setEmailOn} label="Also email the plan" disabled={!emailReady} />
            </div>

            {emailOn && emailReady ? (
              <div className="space-y-3 rounded-card border border-line p-4">
                <Field label="Send to" required help="Up to 10 addresses, separated by commas or spaces.">
                  {(f) => <Input {...f} type="text" value={emailTo} onChange={(e) => setEmailTo(e.target.value)} placeholder="dev@your-company.com, lead@your-company.com" autoComplete="off" />}
                </Field>
                <Field label="Note (optional)">
                  {(f) => <Textarea {...f} value={note} onChange={(e) => setNote(e.target.value)} maxLength={1000} placeholder="Anything the person fixing it should know" />}
                </Field>
              </div>
            ) : null}
          </div>
        ) : null}

        {error ? <p className="rounded-control bg-critical-bg px-3 py-2 text-support text-critical" role="alert">{error}</p> : null}
      </div>
    </Modal>
  );
}
