import { AlertTriangle, CheckCircle2, Info, XCircle } from "lucide-react";
import type { ReactNode } from "react";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/cn";
import { formatDateTime, timeAgo } from "@/lib/format";
import type { CheckResult, SettingsGroup, TestResult } from "@/types/api";
import { VERDICT_LABEL, verdict, type Verdict } from "./model";

const CHECK_ICON = {
  ok: { Icon: CheckCircle2, cls: "text-success", sr: "Passed" },
  warn: { Icon: AlertTriangle, cls: "text-warning", sr: "Warning" },
  fail: { Icon: XCircle, cls: "text-critical", sr: "Failed" },
} as const;

const VERDICT_BOX: Record<Verdict, string> = {
  passed: "border-success/30 bg-success-bg",
  warnings: "border-warning/30 bg-warning-bg",
  failed: "border-critical/30 bg-critical-bg",
};
const VERDICT_ICON: Record<Verdict, keyof typeof CHECK_ICON> = { passed: "ok", warnings: "warn", failed: "fail" };

/** "Fill in the required fields first: " arrives with nothing after the colon when no field is missing by name. */
const tidy = (detail: string): string => detail.replace(/:\s*$/, "");

function CheckLine({ check }: { check: CheckResult }) {
  const { Icon, cls, sr } = CHECK_ICON[check.status];
  return (
    <li className="flex items-start gap-2 text-support">
      <Icon className={cn("mt-px h-4 w-4 shrink-0", cls)} aria-hidden />
      <span className="min-w-0 break-words text-ink">
        <span className="sr-only">{sr}: </span>
        <span className="font-medium">{check.name}</span>
        {check.detail ? <span className="text-ink-2">: {tidy(check.detail)}</span> : null}
      </span>
    </li>
  );
}

/** The result of a connection test: an overall verdict and one line per check. */
export function TestChecks({ result, className }: { result: TestResult; className?: string }) {
  const v = verdict(result);
  const { Icon, cls } = CHECK_ICON[VERDICT_ICON[v]];
  return (
    <div className={cn("rounded-control border p-3", VERDICT_BOX[v], className)} role="status">
      <p className="flex flex-wrap items-center gap-x-2 text-card text-ink">
        <Icon className={cn("h-4 w-4 shrink-0", cls)} aria-hidden />
        <span>Test {VERDICT_LABEL[v]}</span>
        <span className="text-support font-normal text-ink-2" title={formatDateTime(result.tested_at)}>{timeAgo(result.tested_at)}</span>
      </p>
      {result.checks.length > 0 ? (
        <ul className="mt-2 space-y-1.5">
          {result.checks.map((c, i) => (
            <CheckLine key={`${c.name}-${i}`} check={c} />
          ))}
        </ul>
      ) : null}
    </div>
  );
}

/** "Saved 3 h ago. Last tested 5 min ago: passed" for one settings group. */
export function SavedStatus({ group, showTest = true, className }: { group: SettingsGroup; /** false for groups that connect to nothing: they have no test history to report */ showTest?: boolean; className?: string }) {
  const t = group.last_test;
  const v = t ? verdict(t) : null;
  return (
    <p className={cn("text-support text-ink-2", className)}>
      {group.updated_at ? <span title={formatDateTime(group.updated_at)}>Saved {timeAgo(group.updated_at)}. </span> : <span>Not saved yet. </span>}
      {!showTest ? null : t && v ? (
        <span title={formatDateTime(t.tested_at)}>
          Last tested {timeAgo(t.tested_at)}:{" "}
          <span className={cn("font-medium", v === "passed" ? "text-success" : v === "warnings" ? "text-warning" : "text-critical")}>{VERDICT_LABEL[v]}</span>
        </span>
      ) : (
        <span>Not tested yet.</span>
      )}
    </p>
  );
}

export const ConfigBadge = ({ configured }: { configured: boolean }) => (
  <Badge tone={configured ? "success" : "neutral"} dot>{configured ? "Configured" : "Not configured"}</Badge>
);

export type SystemState = "connected" | "error" | "not_connected" | "optional" | "checking" | "unknown";

const STATE_BADGE: Record<SystemState, { tone: "success" | "critical" | "neutral" | "info" | "warning"; label: string }> = {
  connected: { tone: "success", label: "Connected" },
  error: { tone: "critical", label: "Error" },
  not_connected: { tone: "neutral", label: "Not connected" },
  optional: { tone: "neutral", label: "Optional" },
  checking: { tone: "info", label: "Checking" },
  unknown: { tone: "warning", label: "Status unavailable" },
};

export const StateBadge = ({ state }: { state: SystemState }) => (
  <Badge tone={STATE_BADGE[state].tone} dot>{STATE_BADGE[state].label}</Badge>
);

/** Shown instead of a form when the server is single-user: connections come from environment variables, not from the UI. */
export function EnvNote({ children, className }: { children?: ReactNode; className?: string }) {
  return (
    <div className={cn("flex items-start gap-2.5 rounded-card border border-line bg-surface px-4 py-3 text-body text-ink", className)} role="note">
      <Info className="mt-0.5 h-4 w-4 shrink-0 text-ink-2" aria-hidden />
      <div>
        <p className="font-medium">Configured by the server&apos;s environment variables (RAGI_*)</p>
        {children ? <div className="mt-0.5 text-support text-ink-2">{children}</div> : null}
      </div>
    </div>
  );
}
