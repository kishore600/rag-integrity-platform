import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";
import { cn } from "@/lib/cn";
import { Card } from "@/components/ui/card";
import { Skeleton } from "./states";
import type { Tone } from "@/components/ui/badge";

export function PageHeader({ title, description, actions, className }: { title: string; description?: ReactNode; actions?: ReactNode; className?: string }) {
  return (
    <div className={cn("mb-6 flex flex-wrap items-start justify-between gap-4", className)}>
      <div className="min-w-0">
        <h1 className="text-page">{title}</h1>
        {description ? <p className="mt-1 max-w-3xl text-body text-ink-2">{description}</p> : null}
      </div>
      {actions ? <div className="flex flex-wrap items-center gap-2">{actions}</div> : null}
    </div>
  );
}

const iconTone: Record<Tone, string> = {
  neutral: "bg-surface text-ink-2",
  brand: "bg-brand-light text-brand",
  success: "bg-success-bg text-success",
  warning: "bg-warning-bg text-warning",
  critical: "bg-critical-bg text-critical",
  info: "bg-info-bg text-info",
};

export function KpiCard({ label, value, hint, icon: Icon, tone = "brand", loading, onClick }: { label: string; value: ReactNode; hint?: ReactNode; icon?: LucideIcon; tone?: Tone; loading?: boolean; onClick?: () => void }) {
  const body = (
    <>
      <div className="flex items-start justify-between gap-3">
        <p className="text-card text-ink-2">{label}</p>
        {Icon ? (
          <span className={cn("flex h-9 w-9 shrink-0 items-center justify-center rounded-control", iconTone[tone])}>
            <Icon className="h-[18px] w-[18px]" aria-hidden />
          </span>
        ) : null}
      </div>
      {loading ? <Skeleton className="mt-3 h-9 w-24" /> : <p className="mt-2 text-kpi tabular-nums text-ink">{value}</p>}
      {hint ? <div className="mt-1 text-support text-ink-2">{loading ? <Skeleton className="h-4 w-32" /> : hint}</div> : null}
    </>
  );
  if (onClick) {
    return (
      <Card className="p-5 text-left transition-colors hover:border-line-strong hover:bg-surface-hover">
        <button type="button" onClick={onClick} className="block w-full text-left">{body}</button>
      </Card>
    );
  }
  return <Card className="p-5">{body}</Card>;
}

/** Label/value rows for details panels. */
export function KeyValue({ items, className }: { items: { label: string; value: ReactNode }[]; className?: string }) {
  return (
    <dl className={cn("grid grid-cols-1 gap-x-6 gap-y-3 sm:grid-cols-2", className)}>
      {items.map((i) => (
        <div key={i.label} className="min-w-0">
          <dt className="text-support text-ink-2">{i.label}</dt>
          <dd className="mt-0.5 break-words text-body text-ink">{i.value ?? "—"}</dd>
        </div>
      ))}
    </dl>
  );
}

export function Section({ title, description, actions, children, className }: { title: string; description?: ReactNode; actions?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={cn("px-5 py-4", className)}>
      <div className="mb-3 flex items-start justify-between gap-3">
        <div>
          <h3 className="text-card text-ink">{title}</h3>
          {description ? <p className="mt-0.5 text-support text-ink-2">{description}</p> : null}
        </div>
        {actions}
      </div>
      {children}
    </section>
  );
}

export const Mono = ({ children, className }: { children: ReactNode; className?: string }) => (
  <code className={cn("break-all rounded bg-surface px-1.5 py-0.5 font-mono text-support text-ink", className)}>{children}</code>
);

export function ProgressBar({ value, tone = "brand", label }: { value: number; tone?: "brand" | "success" | "warning" | "critical"; label?: string }) {
  const color = { brand: "bg-brand", success: "bg-success", warning: "bg-warning", critical: "bg-critical" }[tone];
  const pct = Math.max(0, Math.min(100, value));
  return (
    <div className="h-2 w-full overflow-hidden rounded-full bg-surface" role="progressbar" aria-valuenow={Math.round(pct)} aria-valuemin={0} aria-valuemax={100} aria-label={label}>
      <div className={cn("h-full rounded-full transition-all", color)} style={{ width: `${pct}%` }} />
    </div>
  );
}

export interface TimelineItem {
  id: string | number;
  title: ReactNode;
  meta?: ReactNode;
  body?: ReactNode;
  tone?: Tone;
  icon?: LucideIcon;
}

const dot: Record<Tone, string> = { neutral: "bg-ink-3", brand: "bg-brand", success: "bg-success", warning: "bg-warning", critical: "bg-critical", info: "bg-info" };

export function Timeline({ items }: { items: TimelineItem[] }) {
  return (
    <ol className="relative space-y-4 border-l border-line pl-5">
      {items.map((i) => (
        <li key={i.id} className="relative">
          <span className={cn("absolute -left-[25px] top-1.5 h-2.5 w-2.5 rounded-full ring-4 ring-workspace", dot[i.tone ?? "neutral"])} aria-hidden />
          <div className="text-body text-ink">{i.title}</div>
          {i.meta ? <div className="text-support text-ink-2">{i.meta}</div> : null}
          {i.body ? <div className="mt-1 text-support text-ink-2">{i.body}</div> : null}
        </li>
      ))}
    </ol>
  );
}
