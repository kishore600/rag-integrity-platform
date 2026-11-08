import { Activity } from "lucide-react";
import { useMemo, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { Card, CardBody } from "@/components/ui/card";
import type { Tone } from "@/components/ui/badge";
import { SearchInput } from "@/components/ui/form";
import { FilterBar, FilterSelect } from "@/components/shared/filters";
import { EmptyState, ErrorState, Skeleton } from "@/components/shared/states";
import { SeverityBadge } from "@/components/shared/status";
import { Timeline, type TimelineItem } from "@/components/shared/page";
import { useHistory } from "@/hooks/queries";
import { formatDateTime, formatNumber, formatPercent, timeAgo } from "@/lib/format";
import { issueLabel } from "@/lib/issue-meta";
import { links } from "@/lib/links";
import type { HistoryEvent } from "@/types/api";
import { documentLabel, humanize, kindLabel } from "./helpers";
import { useClearParams, useUrlParam, useUrlSearch } from "./use-url-state";

const KIND_OPTIONS = [
  { value: "", label: "All activity" },
  { value: "issue", label: "Issues" },
  { value: "repair", label: "Repairs" },
  { value: "audit", label: "Audits" },
];
const PAGE = 50;

const ISSUE_EVENTS: Record<string, { label: string; tone: Tone }> = {
  opened: { label: "Issue opened", tone: "warning" },
  reopened: { label: "Issue reopened", tone: "warning" },
  escalated: { label: "Issue escalated", tone: "critical" },
  severity_changed: { label: "Severity changed", tone: "info" },
  resolved: { label: "Issue resolved", tone: "success" },
  ignored: { label: "Issue ignored", tone: "neutral" },
  unignored: { label: "Issue unignored", tone: "info" },
};

const REPAIR_EVENTS: Record<string, { label: string; tone: Tone }> = {
  created: { label: "Repair plan created", tone: "info" },
  reindex_triggered: { label: "Re-index requested", tone: "info" },
  verified: { label: "Repair verified", tone: "success" },
  cleanup_triggered: { label: "Vector cleanup requested", tone: "info" },
  worker_callback: { label: "Worker callback received", tone: "neutral" },
};

const str = (v: unknown): string | undefined => (typeof v === "string" && v ? v : undefined);
const num = (v: unknown): number | undefined => (typeof v === "number" ? v : undefined);
const plural = (n: number, one: string, many: string) => `${formatNumber(n)} ${n === 1 ? one : many}`;

interface Described {
  label: string;
  tone: Tone;
  heading?: ReactNode;
  lines: ReactNode[];
  search: string;
}

function describe(e: HistoryEvent): Described {
  if (e.kind === "issue") {
    const known = ISSUE_EVENTS[e.event];
    const lines: ReactNode[] = [
      <span key="doc" title={`${e.document_id} in ${e.tenant_id}`}>
        {documentLabel(e.document_id)} · {e.tenant_id} · {issueLabel(e.type)}
      </span>,
    ];
    const from = str(e.details.from);
    const to = str(e.details.to);
    if (e.event === "severity_changed" && from && to) lines.push(<span key="sev">From {from} to {to}</span>);
    const reason = str(e.details.reason);
    if (reason && (e.event === "ignored" || e.event === "unignored")) lines.push(<span key="reason">Reason: {reason}</span>);
    return {
      label: known?.label ?? `Issue ${humanize(e.event).toLowerCase()}`,
      tone: known?.tone ?? "neutral",
      heading: (
        <Link to={links.issue(e.issue_id)} className="text-ink hover:text-brand hover:underline">
          {e.title}
        </Link>
      ),
      lines,
      search: `${e.title} ${e.document_id} ${e.tenant_id} ${e.issue_id} ${e.type} ${issueLabel(e.type)} ${e.run_id ?? ""}`,
    };
  }

  if (e.kind === "repair") {
    const known = REPAIR_EVENTS[e.event];
    const d = e.details;
    const lines: ReactNode[] = [];
    let tone: Tone = known?.tone ?? "neutral";
    const docs = num(d.documents);
    if (e.event === "created") {
      const issues = num(d.issues);
      if (docs !== undefined) lines.push(<span key="n">{plural(docs, "document", "documents")}{issues !== undefined ? `, ${plural(issues, "issue", "issues")}` : ""}</span>);
    } else if (e.event === "reindex_triggered" && docs !== undefined) {
      lines.push(<span key="n">{plural(docs, "document", "documents")} sent to your worker</span>);
    } else if (e.event === "cleanup_triggered") {
      const points = num(d.points);
      if (points !== undefined) lines.push(<span key="n">{plural(points, "vector", "vectors")} to remove{docs !== undefined ? ` across ${plural(docs, "document", "documents")}` : ""}</span>);
    } else if (e.event === "verified") {
      const result = str(d.result);
      const done = num(d.completed);
      const total = num(d.total);
      const failed = num(d.failed);
      if (result) tone = result === "failed" ? "critical" : result === "completed" || result === "cleanup_pending" ? "success" : "warning";
      if (done !== undefined && total !== undefined) lines.push(<span key="n">{done} of {total} documents repaired{failed ? `, ${failed} failed` : ""}</span>);
      const run = str(d.verification_run);
      if (run) {
        lines.push(
          <Link key="run" to={links.audit(run)} className="text-brand hover:underline">
            View the verification audit
          </Link>,
        );
      }
    }
    return { label: known?.label ?? `Repair ${humanize(e.event).toLowerCase()}`, tone, lines, search: `repair ${e.event} ${e.plan_id}` };
  }

  const d = e.details;
  const failed = e.event === "audit_failed";
  const parts: string[] = [`${kindLabel(d.kind)} audit`, humanize(d.trigger).toLowerCase()];
  const tenant = str((d.scope as Record<string, unknown> | undefined)?.tenant);
  if (tenant) parts.push(`tenant ${tenant}`);
  const lines: ReactNode[] = [<span key="what">{parts.join(" · ")}</span>];
  if (!failed && d.findings !== null && d.findings !== undefined) {
    lines.push(<span key="res" className="tabular-nums">{plural(d.findings, "issue", "issues")} found{d.health_score !== null ? `, health ${formatPercent(d.health_score)}` : ""}</span>);
  }
  if (failed && d.error) lines.push(<span key="err" className="text-critical">{d.error}</span>);
  return {
    label: failed ? "Audit failed" : e.event === "audit_completed" ? "Audit completed" : humanize(e.event),
    tone: failed ? "critical" : "success",
    heading: (
      <Link to={links.audit(e.run_id)} className="text-ink hover:text-brand hover:underline">
        View audit
      </Link>
    ),
    lines,
    search: `audit ${d.kind} ${d.trigger} ${e.run_id} ${tenant ?? ""} ${d.error ?? ""}`,
  };
}

function dayLabel(iso: string): string {
  const d = new Date(iso);
  const start = (x: Date) => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime();
  const diff = Math.round((start(new Date()) - start(d)) / 86_400_000);
  if (diff === 0) return "Today";
  if (diff === 1) return "Yesterday";
  return d.toLocaleDateString("en-US", { weekday: "long", month: "long", day: "numeric", year: "numeric" });
}

export function ActivityTab() {
  const q = useHistory(200);
  const [kind, setKind] = useUrlParam("kind");
  const search = useUrlSearch("q");
  const clearParams = useClearParams();
  const [shown, setShown] = useState(PAGE);

  const events = useMemo(() => {
    const needle = search.value.trim().toLowerCase();
    return (q.data ?? [])
      .filter((e) => !kind || e.kind === kind)
      .map((e) => ({ e, d: describe(e) }))
      .filter(({ d }) => !needle || `${d.label} ${d.search}`.toLowerCase().includes(needle));
  }, [q.data, kind, search.value]);

  const groups = useMemo(() => {
    const out: { day: string; items: TimelineItem[] }[] = [];
    events.slice(0, shown).forEach(({ e, d }, i) => {
      const day = e.ts ? dayLabel(e.ts) : "Unknown date";
      let g = out[out.length - 1];
      if (!g || g.day !== day) {
        g = { day, items: [] };
        out.push(g);
      }
      g.items.push({
        id: `${e.kind}-${e.ts}-${i}`,
        tone: d.tone,
        title: (
          <span className="flex flex-wrap items-center gap-2">
            <span className="font-medium">{d.label}</span>
            {e.kind === "issue" ? <SeverityBadge severity={e.severity} /> : null}
          </span>
        ),
        meta: <span title={formatDateTime(e.ts)}>{timeAgo(e.ts)}</span>,
        body: (
          <div className="space-y-0.5">
            {d.heading ? <div className="text-body text-ink">{d.heading}</div> : null}
            {d.lines.map((l, j) => (
              <div key={j} className="break-words">
                {l}
              </div>
            ))}
          </div>
        ),
      });
    });
    return out;
  }, [events, shown]);

  const filtered = !!(kind || search.text);
  function clear() {
    clearParams(["kind", "q"]);
    search.setText("");
    setShown(PAGE);
  }

  return (
    <Card>
      <FilterBar onClear={clear} active={filtered}>
        <div className="min-w-[220px] flex-1 sm:max-w-sm">
          <span className="mb-1 block text-support text-ink-2">Search</span>
          <SearchInput value={search.text} onChange={(v) => { search.setText(v); setShown(PAGE); }} placeholder="Search activity" />
        </div>
        <FilterSelect label="Show" value={kind} onChange={(v) => { setKind(v); setShown(PAGE); }} options={KIND_OPTIONS} />
      </FilterBar>

      {q.isPending ? (
        <CardBody aria-busy aria-label="Loading activity" className="space-y-5">
          {[0, 1, 2, 3, 4].map((i) => (
            <div key={i} className="space-y-1.5">
              <Skeleton className="h-4 w-1/3" />
              <Skeleton className="h-3 w-2/3" />
            </div>
          ))}
        </CardBody>
      ) : q.isError ? (
        <ErrorState error={q.error} onRetry={() => void q.refetch()} />
      ) : events.length === 0 ? (
        filtered ? (
          <EmptyState compact icon={Activity} title="No activity matches" description="Try a different search or clear the filters." />
        ) : (
          <EmptyState icon={Activity} title="No activity yet" description="Issues found, repairs requested and audits that ran are listed here as they happen." />
        )
      ) : (
        <CardBody className="space-y-6">
          {groups.map((g) => (
            <section key={g.day} aria-label={g.day}>
              <h3 className="table-head mb-3">{g.day}</h3>
              <Timeline items={g.items} />
            </section>
          ))}
          <div className="flex flex-wrap items-center justify-between gap-3 border-t border-line pt-4 text-support text-ink-2">
            <span>
              Showing <span className="font-medium tabular-nums text-ink">{Math.min(shown, events.length)}</span> of <span className="font-medium tabular-nums text-ink">{events.length}</span>
              {(q.data?.length ?? 0) >= 200 ? " (the 200 most recent events)" : ""}
            </span>
            {shown < events.length ? (
              <Button variant="secondary" size="sm" onClick={() => setShown((n) => n + PAGE)}>
                Show more
              </Button>
            ) : null}
          </div>
        </CardBody>
      )}
    </Card>
  );
}
