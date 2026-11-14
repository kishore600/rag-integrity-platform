import { ArrowRight, Database, HardDrive, Layers, type LucideIcon } from "lucide-react";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import type { Tone } from "@/components/ui/badge";
import { HealthBadge } from "@/components/shared/status";
import { LinkButton } from "@/components/shared/link-button";
import { cn } from "@/lib/cn";
import { formatDateTime, formatNumber } from "@/lib/format";
import { links } from "@/lib/links";
import type { AuditRun, AuditStats } from "@/types/api";

interface Tile {
  key: string;
  label: string;
  system: string;
  icon: LucideIcon;
  value: number | undefined;
}

const TONE_DOT: Record<Tone, string> = { neutral: "bg-ink-3", brand: "bg-brand", success: "bg-success", warning: "bg-warning", critical: "bg-critical", info: "bg-info" };

/** Plain-language differences, computed only from the three counts the audit recorded. Vectors are chunks, so they are never compared one to one with documents. */
export function differences(s: AuditStats): { tone: Tone; text: string }[] {
  const out: { tone: Tone; text: string }[] = [];
  const { source_documents: src, manifest_rows: man, index_points: idx } = s;
  if (src !== undefined && man !== undefined && s.manifest?.connected !== false) {
    const d = man - src;
    const n = Math.abs(d);
    out.push(
      d === 0
        ? { tone: "success", text: "The manifest lists as many rows as the source has documents." }
        : { tone: "warning", text: `The manifest lists ${formatNumber(n)} ${d < 0 ? "fewer" : "more"} row${n === 1 ? "" : "s"} than the source has documents.` },
    );
  }
  if (idx !== undefined && src !== undefined) {
    if (idx === 0 && src > 0) out.push({ tone: "critical", text: `The index is empty while the source has ${formatNumber(src)} document${src === 1 ? "" : "s"}.` });
    else if (src > 0) out.push({ tone: "neutral", text: `The index holds about ${(idx / src).toFixed(1)} vectors per source document, because each document is split into chunks.` });
  }
  return out;
}

export function ThreeWayCard({ run }: { run: AuditRun }) {
  const s = run.stats;
  const withManifest = s.manifest?.connected !== false; // the manifest is optional: with none there is nothing to count
  const tiles: Tile[] = [
    { key: "source", label: "Source documents", system: "Amazon S3", icon: HardDrive, value: s.source_documents },
    ...(withManifest ? [{ key: "manifest", label: "Manifest rows", system: "PostgreSQL", icon: Database, value: s.manifest_rows }] : []),
    { key: "index", label: "Index vectors", system: "Vector index", icon: Layers, value: s.index_points },
  ];
  const diffs = differences(s);

  return (
    <Card>
      <CardHeader
        title={withManifest ? "Three-way comparison" : "Comparison with the index"}
        description="What each system holds, as counted by the latest full audit."
        actions={
          <LinkButton variant="secondary" size="sm" to={links.audit(run.id)}>
            View audit
          </LinkButton>
        }
      />
      <CardBody className="space-y-5">
        <div className={cn("grid gap-3 md:items-stretch", withManifest ? "md:grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)_auto_minmax(0,1fr)]" : "md:grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)]")}>
          {tiles.map((t, i) => (
            <TileWithArrow key={t.key} tile={t} arrow={i < tiles.length - 1} />
          ))}
        </div>

        {diffs.length > 0 ? (
          <ul className="space-y-2" aria-label="Differences">
            {diffs.map((d) => (
              <li key={d.text} className="flex items-start gap-2.5 text-body text-ink">
                <span className={cn("mt-[7px] h-2 w-2 shrink-0 rounded-full", TONE_DOT[d.tone])} aria-hidden />
                <span>{d.text}</span>
              </li>
            ))}
          </ul>
        ) : null}

        <p className="flex flex-wrap items-center gap-x-2 gap-y-1 border-t border-line pt-4 text-support text-ink-2">
          <span>Finished {formatDateTime(run.finished_at ?? run.started_at)}</span>
          {s.documents_total !== undefined ? (
            <>
              <span aria-hidden>·</span>
              <span className="tabular-nums">{formatNumber(s.documents_total)} documents compared</span>
            </>
          ) : null}
          {s.health_score !== undefined ? (
            <>
              <span aria-hidden>·</span>
              <span className="inline-flex items-center gap-1.5">
                Health score <HealthBadge score={s.health_score} />
              </span>
            </>
          ) : null}
        </p>
      </CardBody>
    </Card>
  );
}

function TileWithArrow({ tile, arrow }: { tile: Tile; arrow: boolean }) {
  const Icon = tile.icon;
  return (
    <>
      <div className="min-w-0 rounded-card border border-line bg-app p-4">
        <div className="flex items-center gap-3">
          <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-control bg-brand-light text-brand">
            <Icon className="h-[18px] w-[18px]" aria-hidden />
          </span>
          <div className="min-w-0">
            <p className="truncate text-card text-ink">{tile.label}</p>
            <p className="truncate text-support text-ink-2">{tile.system}</p>
          </div>
        </div>
        <p className="mt-3 text-kpi tabular-nums text-ink">{formatNumber(tile.value)}</p>
      </div>
      {arrow ? (
        <div className="hidden items-center justify-center md:flex" aria-hidden>
          <ArrowRight className="h-5 w-5 text-ink-3" />
        </div>
      ) : null}
    </>
  );
}
