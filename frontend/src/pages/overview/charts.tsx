import { CheckCircle2, TrendingUp } from "lucide-react";
import { Link } from "react-router-dom";
import { Area, AreaChart, CartesianGrid, Cell, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { EmptyState } from "@/components/shared/states";
import { formatDateTime, formatNumber, formatPercent } from "@/lib/format";
import { links } from "@/lib/links";
import { SEVERITIES } from "@/lib/issue-meta";
import type { Overview, Severity } from "@/types/api";
import { SrTable, capitalize } from "./ui";

// Design tokens as hex: SVG props cannot use Tailwind classes.
const BRAND = "#4F46E5";
const GRID = "#E2E8F0";
const AXIS = { fill: "#64748B", fontSize: 12 };
const SEVERITY_COLOR: Record<Severity, string> = { critical: "#DC2626", high: "#D97706", medium: "#2563EB", low: "#94A3B8", info: "#CBD5E1" };

export const CHART_HEIGHT = 300;

// ---- health over time -----------------------------------------------------------------------------------
interface TrendPoint {
  at: string;
  health: number;
  findings: number | null;
  documents: number | null;
}

const tickTime = (iso: string): string => new Date(iso).toLocaleString("en-US", { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });

function TrendTooltip({ active, payload }: { active?: boolean; payload?: { payload: TrendPoint }[] }) {
  const p = active ? payload?.[0]?.payload : undefined;
  if (!p) return null;
  return (
    <div className="rounded-control border border-line bg-workspace px-3 py-2 text-support shadow-pop">
      <p className="text-ink-2">{formatDateTime(p.at)}</p>
      <p className="mt-0.5 text-card tabular-nums text-ink">{formatPercent(p.health)} healthy</p>
      {p.findings !== null ? <p className="tabular-nums text-ink-2">{formatNumber(p.findings)} issues found</p> : null}
      {p.documents !== null ? <p className="tabular-nums text-ink-2">{formatNumber(p.documents)} documents</p> : null}
    </div>
  );
}

export function HealthTrendCard({ trend }: { trend: Overview["trend"] }) {
  const points: TrendPoint[] = [];
  for (const t of trend) {
    if (t.at && t.health_score !== null) points.push({ at: t.at, health: t.health_score, findings: t.findings, documents: t.documents });
  }
  const floor = points.length ? Math.max(0, Math.floor((Math.min(...points.map((p) => p.health)) - 5) / 10) * 10) : 0;
  const first = points[0];
  const last = points[points.length - 1];

  return (
    <Card className="h-full min-w-0 lg:col-span-2">
      <CardHeader title="Health over time" description="Share of documents that are healthy after each full audit." />
      <CardBody>
        {points.length < 2 ? (
          <EmptyState
            compact
            icon={TrendingUp}
            title="The trend appears after two audits"
            description="Run another audit and this chart will show how your index health changes."
            className="min-h-[300px]"
          />
        ) : (
          <>
            <div style={{ height: CHART_HEIGHT }} className="w-full" aria-hidden>
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={points} margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
                  <defs>
                    <linearGradient id="overview-health-fill" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor={BRAND} stopOpacity={0.22} />
                      <stop offset="100%" stopColor={BRAND} stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid stroke={GRID} vertical={false} />
                  <XAxis dataKey="at" tickFormatter={tickTime} tick={AXIS} tickLine={false} axisLine={{ stroke: GRID }} minTickGap={56} tickMargin={8} />
                  <YAxis domain={[floor, 100]} tickFormatter={(v: number) => `${v}%`} tick={AXIS} tickLine={false} axisLine={false} width={44} />
                  <Tooltip content={<TrendTooltip />} cursor={{ stroke: "#CBD5E1" }} />
                  <Area type="monotone" dataKey="health" stroke={BRAND} strokeWidth={2} fill="url(#overview-health-fill)" dot={{ r: 3, fill: BRAND, strokeWidth: 0 }} activeDot={{ r: 5 }} isAnimationActive={false} />
                </AreaChart>
              </ResponsiveContainer>
            </div>
            <p className="sr-only">
              Health score across {points.length} audits, from {formatPercent(first.health)} on {formatDateTime(first.at)} to {formatPercent(last.health)} on {formatDateTime(last.at)}.
            </p>
            <SrTable
              caption="Health score after each full audit"
              columns={["Audit finished", "Health score", "Issues found"]}
              rows={points.map((p) => [formatDateTime(p.at), formatPercent(p.health), p.findings === null ? "Unknown" : formatNumber(p.findings)])}
            />
          </>
        )}
      </CardBody>
    </Card>
  );
}

// ---- open issues by severity ----------------------------------------------------------------------------
interface Slice {
  key: Severity;
  name: string;
  value: number;
  color: string;
}

function SliceTooltip({ active, payload }: { active?: boolean; payload?: { payload: Slice }[] }) {
  const s = active ? payload?.[0]?.payload : undefined;
  if (!s) return null;
  return (
    <div className="flex items-center gap-2 rounded-control border border-line bg-workspace px-3 py-2 text-support shadow-pop">
      <span className="h-2.5 w-2.5 rounded-sm" style={{ backgroundColor: s.color }} aria-hidden />
      <span className="text-ink-2">{s.name}</span>
      <span className="font-medium tabular-nums text-ink">{formatNumber(s.value)}</span>
    </div>
  );
}

export function SeverityCard({ bySeverity, open }: { bySeverity: Overview["issues"]["by_severity"]; open: number }) {
  const order: Severity[] = bySeverity.info ? [...SEVERITIES, "info"] : SEVERITIES;
  const slices: Slice[] = order.map((key) => ({ key, name: capitalize(key), value: bySeverity[key] ?? 0, color: SEVERITY_COLOR[key] }));
  const drawn = slices.filter((s) => s.value > 0);

  return (
    <Card className="h-full min-w-0">
      <CardHeader title="Open issues by severity" description="Issues that are still open right now." />
      <CardBody>
        {open === 0 ? (
          <EmptyState compact icon={CheckCircle2} title="No open issues" description="Nothing needs attention right now." className="min-h-[300px]" />
        ) : (
          <div>
            <div className="relative mx-auto h-[160px] w-[160px]" aria-hidden>
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Pie data={drawn} dataKey="value" nameKey="name" innerRadius={52} outerRadius={78} paddingAngle={drawn.length > 1 ? 2 : 0} stroke="none" isAnimationActive={false}>
                    {drawn.map((s) => (
                      <Cell key={s.key} fill={s.color} />
                    ))}
                  </Pie>
                  <Tooltip content={<SliceTooltip />} />
                </PieChart>
              </ResponsiveContainer>
              <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center">
                <span className="text-kpi tabular-nums text-ink">{formatNumber(open)}</span>
                <span className="text-support text-ink-2">open</span>
              </div>
            </div>
            <ul className="mt-4 divide-y divide-line border-t border-line">
              {slices.map((s) => (
                <li key={s.key}>
                  <Link
                    to={links.issues({ severity: s.key })}
                    className="-mx-2 flex items-center gap-3 rounded-control px-2 py-2 text-body hover:bg-surface-hover"
                    aria-label={`${s.name}: ${s.value} open issues. View them.`}
                  >
                    <span className="h-2.5 w-2.5 shrink-0 rounded-sm" style={{ backgroundColor: s.color }} aria-hidden />
                    <span className="flex-1 text-ink">{s.name}</span>
                    <span className="font-medium tabular-nums text-ink">{formatNumber(s.value)}</span>
                    <span className="w-10 text-right text-support tabular-nums text-ink-2">{Math.round((s.value / open) * 100)}%</span>
                  </Link>
                </li>
              ))}
            </ul>
            <SrTable caption="Open issues by severity" columns={["Severity", "Open issues"]} rows={slices.map((s) => [s.name, s.value])} />
          </div>
        )}
      </CardBody>
    </Card>
  );
}
