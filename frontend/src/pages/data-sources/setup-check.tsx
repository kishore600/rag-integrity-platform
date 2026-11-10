import { CircleCheck, CircleX, Info, Minus, ScanSearch, ShieldCheck, ShieldX, TriangleAlert, type LucideIcon } from "lucide-react";
import { useEffect } from "react";
import { useLocation } from "react-router-dom";
import { Badge, type Tone } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { KpiCard, ProgressBar } from "@/components/shared/page";
import { ErrorState, Skeleton } from "@/components/shared/states";
import { useSetupCheck } from "@/hooks/queries";
import { cn } from "@/lib/cn";
import { formatDuration, formatNumber, timeAgo } from "@/lib/format";
import type { CoverageLink, SetupCheckItem, SetupCheckResult, SetupCheckStatus, SetupStatus } from "@/types/api";
import { Banner } from "../overview/ui";

/** The address #setup-check scrolls here (the ID warnings on Overview and on an audit's page link to it). */
export const SETUP_CHECK_ID = "setup-check";

const OVERALL: Record<SetupStatus, { tone: "success" | "warning" | "critical"; icon: LucideIcon }> = {
  ready: { tone: "success", icon: ShieldCheck },
  needs_attention: { tone: "warning", icon: TriangleAlert },
  not_ready: { tone: "critical", icon: ShieldX },
};

const ITEM: Record<SetupCheckStatus, { label: string; tone: Tone; icon: LucideIcon; color: string; bar: "success" | "warning" | "critical" | "brand" }> = {
  pass: { label: "Passed", tone: "success", icon: CircleCheck, color: "text-success", bar: "success" },
  warn: { label: "Worth a look", tone: "warning", icon: TriangleAlert, color: "text-warning", bar: "warning" },
  fail: { label: "Needs fixing", tone: "critical", icon: CircleX, color: "text-critical", bar: "critical" },
  na: { label: "Not applicable", tone: "neutral", icon: Minus, color: "text-ink-3", bar: "brand" },
};

const COVERAGE: { key: keyof SetupCheckResult["coverage"]; label: string; hint: string }[] = [
  { key: "source_to_manifest", label: "S3 documents found in the manifest", hint: "have a manifest row with the same ID" },
  { key: "manifest_to_source", label: "Manifest rows with a file in S3", hint: "have a file with the same ID" },
  { key: "source_to_index", label: "S3 documents found in Qdrant", hint: "have pieces in Qdrant under the same ID" },
];

// "Pass" starts at 80% and "fail" below 20% (GUIDE.md section 3.10); colour the tiles the same way.
const coverageTone = (c: CoverageLink | null | undefined): Tone => (!c || c.of === 0 ? "neutral" : c.percent >= 80 ? "success" : c.percent >= 20 ? "warning" : "critical");

const TYPE_LABEL: Record<string, string> = { integer: "whole numbers", digits: "text made of digits", text: "text", decimal: "decimal numbers", other: "other" };

function Check({ item }: { item: SetupCheckItem }) {
  const s = ITEM[item.status];
  const Icon = s.icon;
  return (
    <li className="flex gap-3 py-4 first:pt-0 last:pb-0">
      <Icon className={cn("mt-0.5 h-[18px] w-[18px] shrink-0", s.color)} aria-hidden />
      <div className="min-w-0 flex-1">
        <p className="flex flex-wrap items-center gap-2 text-card text-ink">
          {item.name}
          <Badge tone={s.tone}>{s.label}</Badge>
        </p>
        <p className="mt-1 break-words text-body text-ink-2">{item.detail}</p>
        {item.numbers && item.numbers.of > 0 ? (
          <div className="mt-2 max-w-sm">
            <ProgressBar value={(100 * item.numbers.matched) / item.numbers.of} tone={s.bar} label={`${formatNumber(item.numbers.matched)} of ${formatNumber(item.numbers.of)}`} />
          </div>
        ) : null}
        {item.examples && item.examples.length > 0 ? (
          <ul className="mt-2 space-y-1 overflow-x-auto rounded-control bg-surface px-3 py-2">
            {item.examples.map((e) => (
              <li key={e} className="whitespace-pre-wrap break-all font-mono text-support text-ink">
                {e}
              </li>
            ))}
          </ul>
        ) : null}
        {item.hint ? (
          <p className="mt-2 flex gap-1.5 break-words text-support text-ink-2">
            <Info className="mt-0.5 h-3.5 w-3.5 shrink-0 text-info" aria-hidden />
            <span>{item.hint}</span>
          </p>
        ) : null}
        {item.fix ? (
          <p className="mt-2 break-words text-body text-ink">
            <span className="font-medium">What to do: </span>
            {item.fix}
          </p>
        ) : null}
      </div>
    </li>
  );
}

function CheckList({ items, bare }: { items: SetupCheckItem[]; bare?: boolean }) {
  return (
    <ul className={cn("divide-y divide-line px-4 py-4", bare ? "border-t border-line" : "rounded-card border border-line")}>
      {items.map((c) => (
        <Check key={c.id} item={c} />
      ))}
    </ul>
  );
}

function IdColumn({ title, ids, note }: { title: string; ids: string[] | undefined; note?: string }) {
  return (
    <div className="min-w-0">
      <h4 className="table-head mb-2">{title}</h4>
      {ids && ids.length > 0 ? (
        <ul className="space-y-1">
          {ids.map((id) => (
            <li key={id} className="truncate rounded-control bg-surface px-2.5 py-1.5 font-mono text-support text-ink" title={id}>
              {id}
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-support text-ink-2">No IDs to show.</p>
      )}
      {note ? <p className="mt-2 text-support text-ink-2">{note}</p> : null}
    </div>
  );
}

function whatWasRead(c: SetupCheckResult["counts"]): string[] {
  const out: string[] = [];
  if (c.source_documents != null) {
    const files = c.source_files != null ? ` from ${formatNumber(c.source_files)} files${c.source_files_skipped ? ` (${formatNumber(c.source_files_skipped)} skipped)` : ""}` : "";
    out.push(`S3: ${formatNumber(c.source_documents)} documents${files}.`);
  }
  if (c.manifest_rows != null) out.push(`Manifest: ${formatNumber(c.manifest_rows)} rows for ${formatNumber(c.manifest_documents ?? 0)} documents.`);
  if (c.index_points_sampled != null && c.index_points_sampled > 0) {
    const size = c.index_points_approx != null ? `, out of about ${formatNumber(c.index_points_approx)}` : "";
    out.push(`Qdrant: ${formatNumber(c.index_points_sampled)} points looked at${size}.`);
  }
  return out;
}

function Result({ r }: { r: SetupCheckResult }) {
  const overall = OVERALL[r.status];
  const types = Object.entries(r.id_types_in_index ?? {}).filter(([, n]) => (n ?? 0) > 0);
  const glance = r.ids_at_a_glance ?? {};
  const showGlance = (glance.source?.length ?? 0) + (glance.manifest?.length ?? 0) + (glance.index?.length ?? 0) > 0;
  const showCoverage = COVERAGE.some((c) => r.coverage?.[c.key]);
  const read = whatWasRead(r.counts ?? {});
  const nextSteps = r.next_steps ?? [];
  const checks = r.checks ?? [];
  const limits = r.limits ?? [];
  const rank = (c: SetupCheckItem) => (c.status === "fail" ? 0 : 1);
  const problems = checks.filter((c) => c.status === "fail" || c.status === "warn").sort((a, b) => rank(a) - rank(b));
  const fine = checks.filter((c) => c.status === "pass" || c.status === "na");

  return (
    <div className="space-y-6" role="region" aria-label="Setup check result">
      <Banner tone={overall.tone} icon={overall.icon}>
        <p className="font-medium">{r.headline}</p>
      </Banner>

      {showCoverage ? (
        <div className="grid gap-4 sm:grid-cols-3">
          {COVERAGE.map((c) => {
            const link = r.coverage?.[c.key];
            return (
              <KpiCard
                key={c.key}
                label={c.label}
                tone={coverageTone(link)}
                value={link && link.of > 0 ? `${link.percent}%` : "n/a"}
                hint={link ? (link.of > 0 ? `${formatNumber(link.matched)} of ${formatNumber(link.of)} ${c.hint}` : "There was nothing to compare") : "Could not be measured"}
              />
            );
          })}
        </div>
      ) : null}

      {nextSteps.length > 0 ? (
        <section>
          <h3 className="mb-2 text-card text-ink">What to do next</h3>
          <ol className="list-decimal space-y-1.5 pl-5 text-body text-ink">
            {nextSteps.map((step) => (
              <li key={step} className="pl-1">
                {step}
              </li>
            ))}
          </ol>
        </section>
      ) : null}

      {checks.length > 0 ? (
        <section>
          <h3 className="mb-3 text-card text-ink">The checks</h3>
          {problems.length > 0 ? <CheckList items={problems} /> : null}
          {fine.length > 0 && problems.length > 0 ? (
            // what needs attention comes first; the rest stays one click away
            <details className="group mt-3 rounded-card border border-line">
              <summary className="cursor-pointer select-none rounded-card px-4 py-3 text-body font-medium text-ink-2 hover:bg-surface-hover">
                {fine.length} {fine.length === 1 ? "check" : "checks"} passed or not applicable
              </summary>
              <CheckList items={fine} bare />
            </details>
          ) : fine.length > 0 ? (
            <CheckList items={fine} />
          ) : null}
        </section>
      ) : null}

      {showGlance ? (
        <section>
          <h3 className="text-card text-ink">IDs at a glance</h3>
          <p className="mb-3 mt-0.5 text-support text-ink-2">A few real document IDs from each system. Compare them by eye: the same document should have the same ID in all three.</p>
          <div className="grid gap-5 sm:grid-cols-3">
            <IdColumn title="S3" ids={glance.source} />
            <IdColumn title="Manifest" ids={glance.manifest} />
            <IdColumn
              title="Qdrant"
              ids={glance.index}
              note={types.length > 0 ? `Stored as: ${types.map(([k, n]) => `${TYPE_LABEL[k] ?? k} (${formatNumber(n ?? 0)})`).join(", ")}.` : undefined}
            />
          </div>
        </section>
      ) : null}

      {read.length > 0 || limits.length > 0 ? (
        <section className="space-y-1 text-support text-ink-3">
          {read.map((line) => (
            <p key={line}>{line}</p>
          ))}
          {limits.map((line) => (
            <p key={line}>{line}</p>
          ))}
        </section>
      ) : null}

      <p className="text-support text-ink-3">
        {r.generated_at ? `Checked ${timeAgo(r.generated_at)}` : "Checked just now"}
        {r.duration_seconds != null && r.duration_seconds > 0 ? `, in ${formatDuration(r.duration_seconds)}` : ""}. Nothing was changed or saved.
      </p>
    </div>
  );
}

/**
 * Do S3, the manifest and Qdrant call the same documents by the same ID? Read-only: it lists file names, reads manifest rows and samples Qdrant,
 * stores nothing and is not an audit. It can take up to about two minutes on a big system, so the button works as a progress state.
 */
export function SetupCheckCard() {
  const check = useSetupCheck();
  const { hash } = useLocation();

  // a link from an ID warning (#setup-check) lands on this card. The app frame scrolls a new page to the top in its own effect, which runs
  // after this one, so wait a moment.
  useEffect(() => {
    if (hash !== `#${SETUP_CHECK_ID}`) return;
    const t = window.setTimeout(() => document.getElementById(SETUP_CHECK_ID)?.scrollIntoView({ block: "start" }), 80);
    return () => window.clearTimeout(t);
  }, [hash]);

  return (
    <Card id={SETUP_CHECK_ID} className="scroll-mt-6">
      <CardHeader
        title="Setup check"
        description="Do S3, the manifest and Qdrant call the same documents by the same ID? Run this before you trust an audit. It only reads, and it saves nothing."
        actions={
          <Button variant={check.data ? "secondary" : "primary"} onClick={() => check.mutate()} loading={check.isPending}>
            {check.isPending ? null : <ScanSearch className="h-4 w-4" aria-hidden />}
            {check.isPending ? "Checking" : check.data ? "Check again" : "Check setup"}
          </Button>
        }
      />
      <CardBody>
        {check.isPending ? (
          <div className="space-y-3" role="status" aria-busy>
            <p className="text-body text-ink-2">Reading your three systems. This takes seconds on a small system and up to two minutes on a large one. You can stay on this page.</p>
            <Skeleton className="h-12" />
            <Skeleton className="h-24" />
          </div>
        ) : check.isError ? (
          <ErrorState compact error={check.error} onRetry={() => check.mutate()} />
        ) : check.data ? (
          <Result r={check.data} />
        ) : (
          <p className="max-w-3xl text-body text-ink-2">
            An audit matches documents by their ID, so it is only as good as the ID. If a file is called <span className="font-mono text-support text-ink">2329961.pdf</span> but the manifest says{" "}
            <span className="font-mono text-support text-ink">bill-2329961</span>, every document looks missing. Press <span className="font-medium text-ink">Check setup</span> to see, in plain words, whether
            the three systems line up.
          </p>
        )}
      </CardBody>
    </Card>
  );
}
