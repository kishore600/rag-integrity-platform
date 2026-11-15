import { useEffect, useId, useState, type ReactNode } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/shared/states";
import { useTestSettings } from "@/hooks/queries";
import { errorMessage } from "@/lib/api";
import { cn } from "@/lib/cn";
import { formatNumber } from "@/lib/format";
import type { SettingsGroup, TestResult } from "@/types/api";
import { SavedStatus, SettingsModal, StateBadge, TestChecks, verdict, type SystemStatus } from "../_settings-form";

const isStrings = (v: unknown): v is string[] => Array.isArray(v) && v.every((x) => typeof x === "string");
const isCounts = (v: unknown): v is Record<string, number> => !!v && typeof v === "object" && !Array.isArray(v) && Object.values(v).every((x) => typeof x === "number");

const valueOf = (g: SettingsGroup | undefined, name: string): string | null => {
  const f = g?.fields.find((x) => x.name === name);
  return f && f.value !== null && f.value !== "" ? String(f.value) : null;
};
const saved = (g: SettingsGroup | undefined, name: string): boolean => !!g?.fields.find((x) => x.name === name)?.has_value;
const flag = (ok: boolean, yes: string, no: string): ReactNode => <span className={ok ? "text-success" : "text-warning"}>{ok ? yes : no}</span>;

interface Row {
  label: string;
  value: ReactNode;
}

/** The few non-secret settings worth seeing at a glance. Secrets are only ever reported as saved or missing. */
function settingRows(system: SystemStatus): Row[] {
  const g = system.group;
  switch (system.kind) {
    case "s3":
      return [
        { label: "Bucket", value: valueOf(g, "bucket") ?? "Not set" },
        { label: "Prefix", value: valueOf(g, "prefix") ?? "Whole bucket" },
        { label: "Region", value: valueOf(g, "region") ?? "Not set" },
        ...(valueOf(g, "endpoint_url") ? [{ label: "Endpoint", value: valueOf(g, "endpoint_url") }] : []),
        { label: "Credentials", value: flag(saved(g, "access_key_id") && saved(g, "secret_access_key"), "Saved", "Missing") },
      ];
    case "manifest": {
      const table = valueOf(g, "table");
      const schema = valueOf(g, "schema");
      return [
        { label: "Table", value: table ? `${schema ? `${schema}.` : ""}${table}` : "Server default" },
        { label: "Chunk table", value: valueOf(g, "chunk_table") ?? "Not set" },
        { label: "Connection string", value: flag(saved(g, "database_url"), "Saved", "Missing") },
      ];
    }
    case "pgvector": {
      const table = valueOf(g, "table");
      const schema = valueOf(g, "schema");
      return [
        { label: "Table", value: table ? `${schema ? `${schema}.` : ""}${table}` : "Not set" },
        { label: "Columns", value: valueOf(g, "column_map") ? "Custom mapping" : "Default names" },
        { label: "Distance", value: valueOf(g, "distance") ?? "cosine" },
        { label: "Connection string", value: flag(saved(g, "database_url"), "Saved", "Missing") },
      ];
    }
    case "qdrant":
      return [
        { label: "URL", value: valueOf(g, "url") ?? "Not set" },
        { label: "Collections", value: valueOf(g, "collections") ?? "All collections" },
        { label: "API key", value: saved(g, "api_key") ? <span className="text-success">Saved</span> : "Not set" },
      ];
  }
}

/** Facts the live health check measured, when it measured any. */
function liveRows(system: SystemStatus): Row[] {
  const info = system.connection?.info ?? {};
  const rows: Row[] = [];
  if ((system.kind === "qdrant" || system.kind === "pgvector") && isCounts(info.counts)) {
    const entries = Object.entries(info.counts);
    if (entries.length > 0) {
      const shown = entries.slice(0, 4).map(([name, n]) => `${name} (${formatNumber(n)})`);
      rows.push({ label: system.kind === "pgvector" ? "Rows" : "Points", value: shown.join(", ") + (entries.length > 4 ? `, and ${entries.length - 4} more` : "") });
    }
  }
  if (system.kind === "manifest" && isStrings(info.missing) && info.missing.length > 0) {
    rows.push({ label: "Unmapped columns", value: <span className="text-warning">{info.missing.join(", ")}</span> });
  }
  if (system.kind === "s3" && isStrings(info.sample_keys) && info.sample_keys.length > 0) {
    rows.push({
      label: "Sample keys",
      value: (
        <span className="flex flex-col items-end gap-0.5">
          {info.sample_keys.slice(0, 3).map((k) => (
            <code key={k} className="break-all font-mono text-support">{k}</code>
          ))}
        </span>
      ),
    });
  }
  return rows;
}

function RowList({ rows }: { rows: Row[] }) {
  return (
    <dl className="space-y-1.5">
      {rows.map((r) => (
        <div key={r.label} className="flex items-start justify-between gap-4 text-support">
          <dt className="shrink-0 text-ink-2">{r.label}</dt>
          <dd className="min-w-0 break-all text-right text-ink">{r.value}</dd>
        </div>
      ))}
    </dl>
  );
}

export function SystemCard({ system, appMode, highlight, healthError, className }: { system: SystemStatus; appMode: boolean; highlight?: boolean; healthError?: unknown; className?: string }) {
  const titleId = useId();
  const { group, connection, configured, state } = system;
  const Icon = system.icon;
  const [open, setOpen] = useState(false);
  const [result, setResult] = useState<TestResult | null>(null);
  const test = useTestSettings();

  // a newly saved configuration makes an earlier test result stale
  useEffect(() => setResult(null), [group?.updated_at]);

  const missing = group && !configured && group.updated_at ? group.fields.filter((f) => f.required && !f.has_value).map((f) => f.label) : [];

  function runTest() {
    test.mutate(
      { kind: system.kind },
      {
        onSuccess: (r) => {
          setResult(r);
          const v = verdict(r);
          if (v === "passed") toast.success(`${system.name} connection works`);
          else if (v === "warnings") toast.warning(`${system.name} works, with warnings`, { description: r.checks.find((c) => c.status === "warn")?.detail });
          else toast.error(`${system.name} test failed`, { description: r.checks.find((c) => c.status === "fail")?.detail });
        },
        onError: (err) => toast.error(`Couldn't test ${system.name}`, { description: errorMessage(err) }),
      },
    );
  }

  return (
    <Card className={cn("flex flex-col", highlight && "border-brand ring-2 ring-brand/20", className)} role="group" aria-labelledby={titleId}>
      <div className="flex flex-wrap items-start gap-x-3 gap-y-2 px-5 pt-5">
        <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-control bg-brand-light text-brand">
          <Icon className="h-5 w-5" aria-hidden />
        </span>
        <div className="min-w-[140px] flex-1">
          <p className="text-support text-ink-2">{system.eyebrow}</p>
          <h2 id={titleId} className="text-section text-ink">{system.name}</h2>
        </div>
        <div className="shrink-0">
          <StateBadge state={state} />
        </div>
      </div>

      <div className="flex-1 space-y-4 px-5 py-4">
        {/* live health, as the server measured it just now */}
        <div className="min-h-[40px] text-support">
          {state === "checking" ? (
            <div className="space-y-2" aria-busy>
              <Skeleton className="h-4 w-3/4" />
              <Skeleton className="h-4 w-1/3" />
            </div>
          ) : configured && connection ? (
            <>
              <p className={cn("break-words", connection.ok ? "text-ink" : "text-critical")}>{connection.detail}</p>
              {connection.latency_ms !== null ? <p className="mt-0.5 text-ink-2">Responded in {Math.round(connection.latency_ms)} ms</p> : null}
            </>
          ) : configured && state === "unknown" ? (
            <p className="text-ink-2">Live status is unavailable right now{healthError ? `: ${errorMessage(healthError)}` : "."}</p>
          ) : appMode ? (
            <p className="text-ink-2">{missing.length > 0 ? `Setup is incomplete. Still needed: ${missing.join(", ")}.` : system.blurb}</p>
          ) : (
            <p className="text-ink-2">{connection ? connection.detail : system.blurb}</p>
          )}
        </div>

        {appMode && configured ? <RowList rows={settingRows(system)} /> : null}
        {configured ? <RowList rows={liveRows(system)} /> : null}

        {group && configured ? <SavedStatus group={group} /> : null}
        {result ? <TestChecks result={result} /> : null}
      </div>

      {appMode && group ? (
        <>
          <div className="flex flex-wrap items-center gap-2 border-t border-line px-5 py-3">
            <Button variant={configured ? "secondary" : "primary"} onClick={() => setOpen(true)}>{group.updated_at ? "Edit" : "Configure"}</Button>
            <Button variant="secondary" onClick={runTest} loading={test.isPending} disabled={!configured} aria-label={`Test the saved ${system.name} connection`}>Test</Button>
          </div>
          <SettingsModal group={group} open={open} onOpenChange={setOpen} title={`${system.eyebrow}: ${system.name}`} />
        </>
      ) : null}
    </Card>
  );
}
