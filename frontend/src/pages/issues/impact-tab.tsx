import { Activity, AlertTriangle, Boxes, CheckCircle2, Coins, FileStack, PiggyBank, SearchCheck } from "lucide-react";
import { useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { Badge, type Tone } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Field, Input } from "@/components/ui/form";
import { KpiCard, Mono, ProgressBar } from "@/components/shared/page";
import { EmptyState, Skeleton } from "@/components/shared/states";
import { useBlastRadius, useOverview } from "@/hooks/queries";
import { errorMessage } from "@/lib/api";
import { cn } from "@/lib/cn";
import { documentName, formatNumber, formatPercent, formatUsd } from "@/lib/format";
import { issueLabel } from "@/lib/issue-meta";
import { links } from "@/lib/links";
import type { BlastRadius, BlastScenario } from "@/types/api";
import { cap } from "./labels";

type Kind = BlastScenario["type"];

const SCENARIOS: { kind: Kind; label: string; description: string }[] = [
  { kind: "open_issues", label: "Open issues", description: "Every document that has an open integrity issue right now, and what it would take to fix them." },
  { kind: "config_change", label: "Pipeline change", description: "Which documents would need re-processing if you changed your parser, chunking or embedding model. Enter the pipeline you are thinking of moving to." },
  { kind: "ingestion_failure", label: "Ingestion failure", description: "Which documents the pipeline touched during a time window, for example while a job was failing." },
];

const TARGET_FIELDS: { name: string; label: string; numeric?: boolean; min: number }[] = [
  { name: "parser_version", label: "Parser version", min: 0 },
  { name: "chunking_version", label: "Chunking version", min: 0 },
  { name: "embedding_model", label: "Embedding model", min: 0 },
  { name: "embedding_model_version", label: "Embedding model version", min: 0 },
  { name: "chunk_size", label: "Chunk size (tokens)", numeric: true, min: 1 },
  { name: "chunk_overlap", label: "Chunk overlap (tokens)", numeric: true, min: 0 },
];

const DOC_STATUS_TONE: Record<string, Tone> = { healthy: "success", degraded: "warning", broken: "critical", pending: "info", orphaned: "neutral" };

function buildScenario(kind: Kind, target: Record<string, string>, since: string, until: string): BlastScenario | string {
  if (kind === "open_issues") return { type: "open_issues" };
  if (kind === "config_change") {
    const t: Record<string, string | number> = {};
    for (const f of TARGET_FIELDS) {
      const v = (target[f.name] ?? "").trim();
      if (!v) continue;
      if (f.numeric) {
        const n = Number(v);
        if (!Number.isInteger(n) || n < f.min) return `${f.label} must be a whole number${f.min > 0 ? " above zero" : ""}.`;
        t[f.name] = n;
      } else {
        t[f.name] = v;
      }
    }
    if (Object.keys(t).length === 0) return "Enter at least one setting of the pipeline you want to analyze.";
    return { type: "config_change", target: t };
  }
  if (!since) return "Choose when the failure started.";
  const s = new Date(since);
  if (Number.isNaN(s.getTime())) return "The start time is not a valid date.";
  const out: BlastScenario = { type: "ingestion_failure", since: s.toISOString() };
  if (until) {
    const u = new Date(until);
    if (Number.isNaN(u.getTime())) return "The end time is not a valid date.";
    if (u < s) return "The end time must be after the start time.";
    out.until = u.toISOString();
  }
  return out;
}

function ConfirmedHint({ type }: { type: string }) {
  if (type === "config_change") return <>Index known to differ from the proposed pipeline</>;
  if (type === "ingestion_failure") return <>Already have an open issue</>;
  return <>Have an open issue</>;
}

function Result({ r }: { r: BlastRadius }) {
  const w = r.workload;
  const q = r.queries;
  const typeCounts = Object.entries(r.by_issue_type).sort((a, b) => b[1] - a[1]);
  const maxType = Math.max(1, ...typeCounts.map(([, n]) => n));
  const kpiCount = w.savings_vs_full_reindex_pct !== null ? 5 : 4;

  return (
    <div className="space-y-6" aria-live="polite">
      <p className="text-body text-ink">{r.description}</p>

      <div className={cn("grid gap-4 sm:grid-cols-2", kpiCount === 5 ? "lg:grid-cols-3 xl:grid-cols-5" : "xl:grid-cols-4")}>
        <KpiCard label="Documents affected" icon={FileStack} tone="warning" value={<>{formatNumber(r.documents.affected)} <span className="text-section font-normal text-ink-2">of {formatNumber(r.documents.total)}</span></>} hint={`${formatPercent(r.documents.affected_pct)} of your documents`} />
        <KpiCard label="Confirmed" icon={CheckCircle2} tone="critical" value={formatNumber(r.documents.confirmed)} hint={<ConfirmedHint type={r.scenario.type} />} />
        <KpiCard label="Chunks to regenerate" icon={Boxes} tone="brand" value={formatNumber(w.chunks_to_regenerate)} hint={`${formatNumber(w.estimated_tokens)} tokens`} />
        <KpiCard label="Estimated cost" icon={Coins} tone="info" value={formatUsd(w.estimated_cost_usd)} hint={`Full reindex: ${formatUsd(w.full_corpus.estimated_cost_usd)}`} />
        {w.savings_vs_full_reindex_pct !== null ? <KpiCard label="Savings vs full reindex" icon={PiggyBank} tone="success" value={formatPercent(w.savings_vs_full_reindex_pct)} hint="Compared with re-embedding every document" /> : null}
      </div>
      <p className="-mt-3 text-support text-ink-2">{w.assumptions}</p>

      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader title="Tenants affected" description="Documents affected out of each tenant's total." />
          {r.tenants.length === 0 ? (
            <EmptyState compact title="No tenants affected" description="This scenario does not touch any documents." />
          ) : (
            <div className="max-h-72 overflow-auto">
              <table className="w-full min-w-[360px] text-table" aria-label="Tenants affected">
                <thead>
                  <tr className="border-b border-line bg-app text-left">
                    <th scope="col" className="table-head px-4 py-2.5">Tenant</th>
                    <th scope="col" className="table-head px-4 py-2.5 text-right">Affected</th>
                    <th scope="col" className="table-head px-4 py-2.5 text-right">Total</th>
                    <th scope="col" className="table-head w-32 px-4 py-2.5">Share</th>
                  </tr>
                </thead>
                <tbody>
                  {r.tenants.map((t) => (
                    <tr key={t.tenant_id} className="border-b border-line last:border-0">
                      <td className="max-w-[200px] px-4 py-2.5"><span className="block truncate text-ink" title={t.tenant_id}>{t.tenant_id}</span></td>
                      <td className="px-4 py-2.5 text-right tabular-nums text-ink">{formatNumber(t.affected)}</td>
                      <td className="px-4 py-2.5 text-right tabular-nums text-ink-2">{formatNumber(t.total)}</td>
                      <td className="px-4 py-2.5"><ProgressBar value={t.total ? (100 * t.affected) / t.total : 0} tone="warning" label={`${t.tenant_id}: ${t.affected} of ${t.total} documents affected`} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>

        <Card>
          <CardHeader title="Issues by type" description="Open issues on the affected documents." />
          <CardBody>
            {typeCounts.length === 0 ? (
              <p className="text-body text-ink-2">The affected documents have no open issues.</p>
            ) : (
              <ul className="space-y-3">
                {typeCounts.map(([type, n]) => (
                  <li key={type}>
                    <div className="mb-1 flex items-baseline justify-between gap-3 text-body">
                      <span className="truncate text-ink">{issueLabel(type)}</span>
                      <span className="font-medium tabular-nums text-ink">{formatNumber(n)}</span>
                    </div>
                    <ProgressBar value={(100 * n) / maxType} tone="brand" label={`${issueLabel(type)}: ${n}`} />
                  </li>
                ))}
              </ul>
            )}
            {r.collections.length > 0 ? (
              <div className="mt-5 border-t border-line pt-4">
                <p className="mb-2 text-support text-ink-2">Collections affected</p>
                <div className="flex flex-wrap gap-1.5">
                  {r.collections.map((c) => (
                    <Mono key={c}>{c}</Mono>
                  ))}
                </div>
              </div>
            ) : null}
          </CardBody>
        </Card>
      </div>

      <Card>
        <CardHeader title="Query impact" description={`Recent searches that returned an affected document (last ${q.window_days} days).`} />
        <CardBody>
          {q.queries_in_window === 0 ? (
            <div className="flex items-start gap-3 text-body text-ink-2">
              <Activity className="mt-0.5 h-4 w-4 shrink-0 text-ink-3" aria-hidden />
              <p>
                No query log has been ingested yet, so the effect on real searches can't be measured. Send your retrieval logs to <Mono>POST /api/query-log</Mono> and this section will show how many queries touched the affected documents.
              </p>
            </div>
          ) : (
            <div className="space-y-5">
              <div className="flex flex-wrap items-end gap-x-8 gap-y-3">
                <div>
                  <p className="text-kpi tabular-nums text-ink">
                    {formatNumber(q.affected_queries)} <span className="text-section font-normal text-ink-2">of {formatNumber(q.queries_in_window)} queries</span>
                  </p>
                  <p className="mt-1 text-support text-ink-2">{q.affected_pct === null ? "No percentage available" : `${formatPercent(q.affected_pct)} of queries in the window returned an affected document`}</p>
                </div>
              </div>
              {q.top_documents.length > 0 ? (
                <div>
                  <p className="mb-2 text-support font-medium text-ink-2">Most requested affected documents</p>
                  <ul className="divide-y divide-line rounded-control border border-line">
                    {q.top_documents.map((d) => (
                      <li key={`${d.tenant_id}/${d.document_id}`} className="flex items-center justify-between gap-3 px-3 py-2.5">
                        <Link to={links.document(d.tenant_id, d.document_id)} className="min-w-0 text-brand hover:underline">
                          <span className="block truncate text-body font-medium" title={d.document_id}>{documentName(d.document_id)}</span>
                          <span className="block truncate text-support text-ink-2" title={d.tenant_id}>{d.tenant_id}</span>
                        </Link>
                        <span className="shrink-0 text-body tabular-nums text-ink">{formatNumber(d.queries)} quer{d.queries === 1 ? "y" : "ies"}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              ) : null}
              {q.note ? <p className="text-support text-ink-2">{q.note}</p> : null}
            </div>
          )}
        </CardBody>
      </Card>

      <Card>
        <CardHeader title="Affected documents" description={r.sample.length < r.documents.affected ? `A sample of ${formatNumber(r.sample.length)} of ${formatNumber(r.documents.affected)} affected documents.` : "Every affected document."} />
        {r.sample.length === 0 ? (
          <EmptyState compact title="No documents affected" description="Nothing in your index matches this scenario." />
        ) : (
          <ul className="divide-y divide-line">
            {r.sample.map((d) => (
              <li key={`${d.tenant_id}/${d.document_id}`}>
                <Link to={links.document(d.tenant_id, d.document_id)} className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 px-5 py-3 hover:bg-surface-hover">
                  <span className="min-w-0">
                    <span className="block truncate text-body font-medium text-brand" title={d.document_id}>{documentName(d.document_id)}</span>
                    <span className="block truncate text-support text-ink-2" title={d.tenant_id}>{d.tenant_id}</span>
                  </span>
                  <span className="flex shrink-0 items-center gap-2">
                    <Badge tone={DOC_STATUS_TONE[d.status] ?? "neutral"} dot>{cap(d.status)}</Badge>
                    <Badge tone={d.confirmed ? "critical" : "neutral"}>{d.confirmed ? "Confirmed" : "Possible"}</Badge>
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}

export function ImpactTab() {
  const overview = useOverview();
  const blast = useBlastRadius();
  const [kind, setKind] = useState<Kind>("open_issues");
  const [target, setTarget] = useState<Record<string, string>>({});
  const [since, setSince] = useState("");
  const [until, setUntil] = useState("");
  const [formError, setFormError] = useState<string | null>(null);

  const current = SCENARIOS.find((s) => s.kind === kind)!;
  const currentTarget = overview.data?.target_fingerprint ?? null;

  function pick(k: Kind) {
    if (k === kind) return;
    setKind(k);
    setFormError(null);
    blast.reset();
  }

  function submit(e: FormEvent) {
    e.preventDefault();
    const scenario = buildScenario(kind, target, since, until);
    if (typeof scenario === "string") {
      setFormError(scenario);
      return;
    }
    setFormError(null);
    blast.mutate(scenario);
  }

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader title="Impact analysis" description="See how much of your index a change or a failure would touch, and what repairing it would cost, before you do anything." />
        <CardBody>
          <form onSubmit={submit} noValidate className="space-y-5">
            <div>
              <p id="scenario-label" className="mb-1.5 text-support font-medium text-ink">Scenario</p>
              <div role="radiogroup" aria-labelledby="scenario-label" className="inline-flex max-w-full flex-wrap rounded-control border border-line-strong bg-surface p-0.5">
                {SCENARIOS.map((s) => {
                  const on = s.kind === kind;
                  return (
                    <button
                      key={s.kind}
                      type="button"
                      role="radio"
                      aria-checked={on}
                      onClick={() => pick(s.kind)}
                      className={cn("rounded-[5px] px-3.5 py-1.5 text-body font-medium transition-colors", on ? "bg-workspace text-brand shadow-card" : "text-ink-2 hover:text-ink")}
                    >
                      {s.label}
                    </button>
                  );
                })}
              </div>
              <p className="mt-2 max-w-2xl text-support text-ink-2">{current.description}</p>
            </div>

            {kind === "config_change" ? (
              <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
                {TARGET_FIELDS.map((f) => {
                  const live = currentTarget?.[f.name];
                  return (
                    <Field key={f.name} label={f.label} help={live !== undefined ? `Current target: ${String(live)}` : undefined}>
                      {(p) => (
                        <Input
                          {...p}
                          type={f.numeric ? "number" : "text"}
                          inputMode={f.numeric ? "numeric" : undefined}
                          min={f.numeric ? f.min : undefined}
                          value={target[f.name] ?? ""}
                          onChange={(e) => setTarget((prev) => ({ ...prev, [f.name]: e.target.value }))}
                          placeholder={live !== undefined ? String(live) : undefined}
                        />
                      )}
                    </Field>
                  );
                })}
              </div>
            ) : null}

            {kind === "ingestion_failure" ? (
              <div className="grid gap-4 sm:grid-cols-2 lg:max-w-2xl">
                <Field label="Started at" required help="Your local time.">
                  {(p) => <Input {...p} type="datetime-local" value={since} onChange={(e) => setSince(e.target.value)} />}
                </Field>
                <Field label="Ended at" help="Leave empty for until now.">
                  {(p) => <Input {...p} type="datetime-local" value={until} onChange={(e) => setUntil(e.target.value)} />}
                </Field>
              </div>
            ) : null}

            {formError ? (
              <p className="rounded-control bg-critical-bg px-3 py-2 text-support text-critical" role="alert">{formError}</p>
            ) : null}
            {blast.isError ? (
              <p className="flex items-start gap-2 rounded-control bg-critical-bg px-3 py-2 text-support text-critical" role="alert">
                <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
                {errorMessage(blast.error)}
              </p>
            ) : null}

            <Button type="submit" variant="primary" loading={blast.isPending}>
              <SearchCheck className="h-4 w-4" aria-hidden /> Analyze impact
            </Button>
          </form>
        </CardBody>
      </Card>

      {blast.isPending ? (
        <div className="space-y-3" aria-busy aria-label="Analyzing impact">
          <Skeleton className="h-28 w-full" />
          <Skeleton className="h-48 w-full" />
        </div>
      ) : blast.data ? (
        <Result r={blast.data} />
      ) : !blast.isError ? (
        <Card>
          <EmptyState
            icon={Activity}
            title="Run an analysis to see the impact"
            description="Pick a scenario above and choose Analyze impact. RAGGuard reads your latest audit results, so nothing in your systems is touched and nothing is changed."
          />
        </Card>
      ) : null}
    </div>
  );
}
