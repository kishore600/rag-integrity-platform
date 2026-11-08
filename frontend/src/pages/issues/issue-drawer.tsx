import { FileSearch, RotateCcw } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Drawer } from "@/components/ui/overlays";
import { KeyValue, Mono, Section, Timeline, type TimelineItem } from "@/components/shared/page";
import { EmptyState, ErrorState, Skeleton } from "@/components/shared/states";
import { IssueStatusBadge, SeverityBadge } from "@/components/shared/status";
import { LinkButton } from "@/components/shared/link-button";
import { useCreatePlan, useIgnoreIssue, useIssue, useReopenIssue } from "@/hooks/queries";
import { ApiError, errorMessage } from "@/lib/api";
import { documentName, formatDateTime, formatNumber, shortHash, timeAgo } from "@/lib/format";
import { ISSUE_META, REMEDIATION, describeStates, issueLabel, issueSources } from "@/lib/issue-meta";
import { links } from "@/lib/links";
import type { IssueDetail, Severity } from "@/types/api";
import { ACTION_LABEL, describeIssueEvent, evidenceFacts, isSeverity } from "./labels";
import { IgnoreDialog } from "./parts";

const num = (v: unknown): number | undefined => (typeof v === "number" ? v : undefined);

// ---- evidence -----------------------------------------------------------------------------------------------
function ProbeView({ probe }: { probe: NonNullable<IssueDetail["evidence"]["retrieval_probe"]> }) {
  const results = Array.isArray(probe.results) ? probe.results : [];
  const rank = typeof probe.rank === "number" ? probe.rank : null;
  return (
    <div>
      <h4 className="mb-2 text-support font-medium text-ink-2">Retrieval probe</h4>
      <KeyValue
        items={[
          { label: "Reachable", value: probe.reachable === undefined ? "—" : probe.reachable ? "Yes" : "No" },
          { label: "Rank in results", value: rank !== null ? `#${rank}${probe.top_k ? ` of top ${probe.top_k}` : ""}` : probe.top_k ? `Not in the top ${probe.top_k}` : "Not found" },
          { label: "Score", value: typeof probe.score === "number" ? probe.score.toFixed(3) : "—" },
          { label: "Tenant filter", value: probe.tenant_filter ? <Mono>{probe.tenant_filter}</Mono> : "None" },
          ...(probe.method ? [{ label: "Method", value: probe.method }] : []),
        ]}
      />
      {probe.error ? <p className="mt-3 rounded-control bg-critical-bg px-3 py-2 text-support text-critical">{probe.error}</p> : null}
      {results.length > 0 ? (
        <div className="mt-3 overflow-x-auto rounded-control border border-line">
          <table className="w-full min-w-[420px] text-table" aria-label="Retrieval probe results">
            <thead>
              <tr className="border-b border-line bg-app text-left">
                <th scope="col" className="table-head w-16 px-3 py-2">Rank</th>
                <th scope="col" className="table-head px-3 py-2">Document</th>
                <th scope="col" className="table-head w-20 px-3 py-2 text-right">Score</th>
                <th scope="col" className="table-head w-32 px-3 py-2">Stale content</th>
              </tr>
            </thead>
            <tbody>
              {results.map((r, i) => (
                <tr key={`${r.rank}-${i}`} className="border-b border-line last:border-0">
                  <td className="px-3 py-2 tabular-nums text-ink-2">{r.rank}</td>
                  <td className="max-w-[260px] px-3 py-2">
                    <span className="block truncate text-ink" title={r.document_id ?? undefined}>{r.document_id ? documentName(r.document_id) : "—"}</span>
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums text-ink">{typeof r.score === "number" ? r.score.toFixed(3) : "—"}</td>
                  <td className="px-3 py-2">{r.is_stale_content ? <Badge tone="warning">Stale content</Badge> : <span className="text-ink-3">No</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </div>
  );
}

function EvidenceView({ evidence }: { evidence: IssueDetail["evidence"] }) {
  const ev = evidence ?? {};
  const probe = ev.retrieval_probe && typeof ev.retrieval_probe === "object" ? ev.retrieval_probe : null;
  const problems = Array.isArray(ev.problems) ? ev.problems : [];
  const removalCount = num(ev.removal_count);
  const removalPoints = ev.removal_points && typeof ev.removal_points === "object" ? Object.entries(ev.removal_points).filter(([, ids]) => Array.isArray(ids)) : [];
  const missing = Array.isArray(ev.missing_chunks) ? ev.missing_chunks.filter((c): c is string => typeof c === "string") : [];
  const missingTotal = Math.max(missing.length, num(ev.missing_count) ?? 0);
  const facts = evidenceFacts(ev);
  const hasAny = Object.keys(ev).length > 0;

  if (!hasAny) return <p className="text-body text-ink-2">No evidence was recorded for this issue.</p>;

  return (
    <div className="space-y-5">
      {facts.length > 0 ? (
        <KeyValue
          items={facts.map((f) => ({
            label: f.label,
            value: f.list ? (
              <span className="flex flex-wrap gap-1.5">
                {f.list.map((x) => (
                  <Mono key={x}>{x}</Mono>
                ))}
              </span>
            ) : f.full ? (
              <span title={f.full}><Mono>{f.value}</Mono></span>
            ) : (
              f.value
            ),
          }))}
        />
      ) : null}

      {probe ? <ProbeView probe={probe} /> : null}

      {problems.length > 0 ? (
        <div>
          <h4 className="mb-2 text-support font-medium text-ink-2">Problems found</h4>
          <ul className="divide-y divide-line rounded-control border border-line">
            {problems.map((p, i) => (
              <li key={`${p.code}-${i}`} className="flex flex-wrap items-start gap-x-3 gap-y-1 px-3 py-2.5">
                <SeverityBadge severity={isSeverity(p.severity) ? (p.severity as Severity) : "info"} />
                <Mono>{p.code}</Mono>
                <p className="min-w-0 flex-1 basis-full text-body text-ink sm:basis-0">{p.message}</p>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {removalCount !== undefined || removalPoints.length > 0 ? (
        <div>
          <h4 className="mb-2 text-support font-medium text-ink-2">Vectors to remove</h4>
          {removalCount !== undefined ? <p className="text-body text-ink"><span className="font-semibold tabular-nums">{formatNumber(removalCount)}</span> vector{removalCount === 1 ? "" : "s"} in total</p> : null}
          {removalPoints.length > 0 ? (
            <ul className="mt-2 space-y-1.5">
              {removalPoints.map(([coll, ids]) => (
                <li key={coll} className="flex flex-wrap items-center gap-2 text-body text-ink">
                  <Mono>{coll}</Mono>
                  <span className="tabular-nums text-ink-2">{formatNumber((ids as unknown[]).length)} vector{(ids as unknown[]).length === 1 ? "" : "s"}</span>
                </li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : null}

      {missing.length > 0 ? (
        <div>
          <h4 className="mb-2 text-support font-medium text-ink-2">Missing chunks</h4>
          <div className="flex flex-wrap gap-1.5">
            {missing.slice(0, 20).map((c) => (
              <Mono key={c}>{c}</Mono>
            ))}
            {missingTotal > 20 ? <span className="self-center text-support text-ink-2">+{formatNumber(missingTotal - 20)} more</span> : null}
          </div>
        </div>
      ) : null}

      <details className="group rounded-control border border-line">
        <summary className="cursor-pointer select-none px-3 py-2 text-support font-medium text-ink-2 hover:text-ink">Raw evidence (JSON)</summary>
        <pre className="max-h-72 overflow-auto border-t border-line bg-surface p-3 text-support text-ink">{JSON.stringify(ev, null, 2)}</pre>
      </details>
    </div>
  );
}

// ---- body ---------------------------------------------------------------------------------------------------
/** describeStates reads the stored evidence; if an old or odd record does not fit, show the issue text instead of failing. */
function safeStates(issue: IssueDetail): { expected: string; actual: string } {
  try {
    return describeStates(issue);
  } catch {
    return { expected: "The source, manifest and index agree", actual: issue.title };
  }
}

function IssueBody({ issue }: { issue: IssueDetail }) {
  const meta = ISSUE_META[issue.type];
  const states = safeStates(issue);
  const sources = issueSources(issue.type);
  const wholeCollection = issue.document_id === "*";

  const events: TimelineItem[] = (issue.events ?? []).map((e) => {
    const d = describeIssueEvent(e);
    return {
      id: e.id,
      title: d.title,
      tone: d.tone,
      body: d.body,
      meta: (
        <>
          <span title={formatDateTime(e.ts)}>{formatDateTime(e.ts)}</span>
          {e.run_id ? (
            <>
              {" · "}
              <Link to={links.audit(e.run_id)} className="text-brand hover:underline">View audit run</Link>
            </>
          ) : null}
        </>
      ),
    };
  });

  return (
    <div className="divide-y divide-line">
      <Section title="What's wrong">
        <p className="whitespace-pre-wrap text-body text-ink">{issue.detail}</p>
      </Section>

      <Section title="Why it matters">
        <p className="text-body text-ink">{meta?.why ?? "RAGGuard found a difference between your source, manifest and index."}</p>
      </Section>

      <Section title="Expected vs actual">
        <div className="grid gap-3 sm:grid-cols-2">
          <div className="rounded-control border border-success/30 bg-success-bg p-3">
            <p className="text-support font-medium text-success">Expected</p>
            <p className="mt-1 text-body text-ink">{states.expected}</p>
          </div>
          <div className="rounded-control border border-critical/30 bg-critical-bg p-3">
            <p className="text-support font-medium text-critical">Actual</p>
            <p className="mt-1 text-body text-ink">{states.actual}</p>
          </div>
        </div>
      </Section>

      <Section title="Affected systems">
        <div className="flex flex-wrap gap-2">
          {sources.map((s) => (
            <Badge key={s} tone="neutral">{s}</Badge>
          ))}
        </div>
        <div className="mt-3 text-body">
          {wholeCollection ? (
            <p className="text-ink-2">
              This finding applies to the whole collection{issue.collection ? <> <Mono>{issue.collection}</Mono></> : null}, not to one document.
            </p>
          ) : (
            <Link to={links.document(issue.tenant_id, issue.document_id)} className="inline-flex max-w-full flex-col text-brand hover:underline">
              <span className="truncate font-medium" title={issue.document_id}>{documentName(issue.document_id)}</span>
              <span className="truncate text-support text-ink-2" title={issue.document_id}>{issue.tenant_id} · {issue.document_id}</span>
            </Link>
          )}
          {!wholeCollection && issue.collection ? <p className="mt-2 text-support text-ink-2">Collection <Mono>{issue.collection}</Mono></p> : null}
        </div>
      </Section>

      <Section title="Evidence" description="What RAGGuard read from your systems when it found this.">
        <EvidenceView evidence={issue.evidence} />
      </Section>

      <Section title="Recommended fix">
        <div className="flex flex-wrap items-center gap-2">
          <Badge tone="brand">{ACTION_LABEL[issue.action] ?? issue.action}</Badge>
        </div>
        <p className="mt-2 text-body text-ink">{REMEDIATION[issue.action] ?? "Review this issue and decide how to fix it."}</p>
        {wholeCollection ? <p className="mt-2 text-support text-ink-2">A whole-collection finding can't become an automatic repair plan. Fix it in your own systems, then run another audit.</p> : null}
      </Section>

      <Section title="Timeline">
        <KeyValue
          className="mb-5"
          items={[
            { label: "First seen", value: <span title={formatDateTime(issue.first_seen_at)}>{formatDateTime(issue.first_seen_at)} <span className="text-ink-2">({timeAgo(issue.first_seen_at)})</span></span> },
            { label: "Last seen", value: <span title={formatDateTime(issue.last_seen_at)}>{formatDateTime(issue.last_seen_at)} <span className="text-ink-2">({timeAgo(issue.last_seen_at)})</span></span> },
            { label: "Seen in audits", value: <span className="tabular-nums">{formatNumber(issue.occurrences)}</span> },
            { label: "Reopened", value: <span className="tabular-nums">{issue.reopened_count === 0 ? "Never" : `${issue.reopened_count} time${issue.reopened_count === 1 ? "" : "s"}`}</span> },
            ...(issue.resolved_at
              ? [
                  {
                    label: "Resolved",
                    value: (
                      <span>
                        {formatDateTime(issue.resolved_at)}
                        {issue.resolved_run_id ? (
                          <>
                            {" · "}
                            <Link to={links.audit(issue.resolved_run_id)} className="text-brand hover:underline" title={`Audit run ${shortHash(issue.resolved_run_id)}`}>View audit run</Link>
                          </>
                        ) : null}
                      </span>
                    ),
                  },
                ]
              : []),
            ...(issue.status === "ignored" ? [{ label: "Ignored because", value: issue.ignored_reason ? issue.ignored_reason : "No reason given" }] : []),
          ]}
        />
        {events.length > 0 ? <Timeline items={events} /> : <p className="text-body text-ink-2">No events have been recorded yet.</p>}
      </Section>
    </div>
  );
}

function DrawerSkeleton() {
  return (
    <div className="divide-y divide-line" aria-busy aria-label="Loading issue">
      {["h-12", "h-16", "h-20", "h-14", "h-28"].map((h, i) => (
        <div key={i} className="space-y-3 px-5 py-4">
          <Skeleton className="h-4 w-32" />
          <Skeleton className={`w-full ${h}`} />
        </div>
      ))}
    </div>
  );
}

// ---- drawer ----------------------------------------------------------------------------------------------------
export function IssueDrawer({ id, onClose }: { id: string; onClose: () => void }) {
  const navigate = useNavigate();
  const query = useIssue(id);
  const createPlan = useCreatePlan();
  const ignore = useIgnoreIssue();
  const reopen = useReopenIssue();
  const [ignoreOpen, setIgnoreOpen] = useState(false);
  const issue = query.data;
  const notFound = query.error instanceof ApiError && query.error.status === 404;

  async function makePlan() {
    try {
      const plan = await createPlan.mutateAsync({ issue_ids: [id] });
      toast.success("Repair plan created", { description: "Review it, then trigger the repair." });
      navigate(links.issues({ view: "plans", plan: plan.id }));
    } catch (err) {
      toast.error("Couldn't create the repair plan", { description: errorMessage(err) });
    }
  }

  async function doIgnore(reason: string) {
    await ignore.mutateAsync({ id, reason: reason || undefined });
    toast.success("Issue ignored");
  }

  async function doReopen() {
    try {
      await reopen.mutateAsync(id);
      toast.success("Issue reopened");
    } catch (err) {
      toast.error("Couldn't reopen the issue", { description: errorMessage(err) });
    }
  }

  const canPlan = !!issue && issue.status === "open" && issue.document_id !== "*";

  return (
    <>
      <Drawer
        open
        onOpenChange={(o) => {
          if (!o) onClose();
        }}
        width="xl"
        title={issue ? <span title={issue.title}>{issue.title}</span> : notFound ? "Issue not found" : query.isError ? "Couldn't load this issue" : "Loading issue"}
        description={
          issue ? (
            <span className="flex flex-wrap items-center gap-2">
              <SeverityBadge severity={issue.severity} />
              <IssueStatusBadge status={issue.status} />
              <span>{issueLabel(issue.type)}</span>
            </span>
          ) : undefined
        }
        footer={
          issue ? (
            <>
              {issue.document_id !== "*" ? (
                <LinkButton variant="secondary" to={links.document(issue.tenant_id, issue.document_id)} className="mr-auto">
                  <FileSearch className="h-4 w-4" aria-hidden /> View document
                </LinkButton>
              ) : null}
              {issue.status === "open" ? (
                <Button variant="secondary" onClick={() => setIgnoreOpen(true)}>Ignore</Button>
              ) : (
                <Button variant="secondary" onClick={doReopen} loading={reopen.isPending}>
                  <RotateCcw className="h-4 w-4" aria-hidden /> Reopen
                </Button>
              )}
              {canPlan ? (
                <Button variant="primary" onClick={makePlan} loading={createPlan.isPending}>Create repair plan</Button>
              ) : null}
            </>
          ) : undefined
        }
      >
        {query.isPending ? (
          <DrawerSkeleton />
        ) : notFound ? (
          <EmptyState title="Issue not found" description="It may belong to another workspace, or it was removed. Go back to the list to pick another." action={<Button variant="secondary" onClick={onClose}>Back to issues</Button>} />
        ) : query.isError ? (
          <ErrorState error={query.error} onRetry={() => void query.refetch()} compact />
        ) : issue ? (
          <IssueBody issue={issue} />
        ) : null}
      </Drawer>
      {issue ? <IgnoreDialog open={ignoreOpen} onOpenChange={setIgnoreOpen} count={1} onConfirm={doIgnore} /> : null}
    </>
  );
}
