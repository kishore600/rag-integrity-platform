import { RefreshCw, Server } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { PageHeader } from "@/components/shared/page";
import { Skeleton } from "@/components/shared/states";
import { useSaveSettings } from "@/hooks/queries";
import { errorMessage } from "@/lib/api";
import { cn } from "@/lib/cn";
import type { ConnectionStatus } from "@/types/api";
import { EnvNote, QueryGate, StateBadge, useSystems, type IndexType, type SystemStatus } from "../_settings-form";
import { SetupCheckCard } from "./setup-check";
import { SetupGuide, TrustPoints } from "./setup-guide";
import { SystemCard } from "./system-card";

function CardsSkeleton() {
  return (
    <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3" aria-busy aria-label="Loading data sources">
      {[0, 1, 2].map((i) => (
        <Skeleton key={i} className={cn("h-72", i === 2 && "md:col-span-2 xl:col-span-1")} />
      ))}
    </div>
  );
}

function LedgerCard({ ledger }: { ledger: ConnectionStatus }) {
  const engine = typeof ledger.info.engine === "string" ? ledger.info.engine : null;
  return (
    <Card>
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2 px-5 py-4">
        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-control bg-surface text-ink-2">
          <Server className="h-[18px] w-[18px]" aria-hidden />
        </span>
        <div className="min-w-0 flex-1">
          <h2 className="text-card text-ink">Issue ledger</h2>
          <p className="text-support text-ink-2">
            Where audit runs, issues and repair plans are stored. The server manages it.{engine ? ` Engine: ${engine}.` : ""}
          </p>
          <p className={cn("mt-0.5 break-words text-support", ledger.ok ? "text-ink-2" : "text-critical")}>{ledger.detail}</p>
        </div>
        <StateBadge state={ledger.ok ? "connected" : "error"} />
      </div>
    </Card>
  );
}

/** "Where are your vectors stored?": Qdrant or pgvector. Saved on its own, so the card below it changes at once. */
function IndexChoice({ indexType }: { indexType: IndexType }) {
  const save = useSaveSettings();
  function choose(type: IndexType) {
    if (type === indexType || save.isPending) return;
    save.mutate({ kind: "index", values: { type } }, { onError: (err) => toast.error("Couldn't save that choice", { description: errorMessage(err) }) });
  }
  const options: { value: IndexType; label: string; hint: string }[] = [
    { value: "qdrant", label: "Qdrant", hint: "A Qdrant server or Qdrant Cloud" },
    { value: "pgvector", label: "pgvector (PostgreSQL)", hint: "A table with a vector column: Supabase, Neon, AWS RDS, Postgres" },
  ];
  return (
    <Card>
      <div className="px-5 py-4">
        <h2 className="text-card text-ink" id="index-choice">Where are your vectors stored?</h2>
        <div role="radiogroup" aria-labelledby="index-choice" className="mt-3 grid gap-3 sm:grid-cols-2">
          {options.map((o) => {
            const on = o.value === indexType;
            return (
              <button
                key={o.value}
                type="button"
                role="radio"
                aria-checked={on}
                disabled={save.isPending}
                onClick={() => choose(o.value)}
                className={cn("rounded-card border p-3 text-left transition-colors", on ? "border-brand bg-brand-light" : "border-line bg-workspace hover:bg-surface")}
              >
                <span className="flex items-center gap-2 text-body font-medium text-ink">
                  <span className={cn("flex h-4 w-4 items-center justify-center rounded-full border", on ? "border-brand" : "border-ink-3")} aria-hidden>
                    {on ? <span className="h-2 w-2 rounded-full bg-brand" /> : null}
                  </span>
                  {o.label}
                </span>
                <span className="mt-1 block text-support text-ink-2">{o.hint}</span>
              </button>
            );
          })}
        </div>
      </div>
    </Card>
  );
}

function SystemGrid({ systems, appMode, healthError }: { systems: SystemStatus[]; appMode: boolean; healthError?: unknown }) {
  const current = appMode ? systems.find((s) => !s.configured && !s.optional)?.kind : undefined;
  return (
    <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
      {systems.map((s, i) => (
        <SystemCard key={s.kind} system={s} appMode={appMode} highlight={current === s.kind} healthError={healthError} className={i === 2 ? "md:col-span-2 xl:col-span-1" : undefined} />
      ))}
    </div>
  );
}

export default function DataSourcesPage() {
  const { appMode, settings, connections, systems, indexType, ledger, refresh, fetching } = useSystems();

  const header = (
    <PageHeader
      title="Data sources"
      description="Your documents and your vector index, plus an optional manifest: the systems RAGGuard compares."
      actions={
        <Button variant="secondary" onClick={() => void refresh()} disabled={fetching}>
          <RefreshCw className={cn("h-4 w-4", fetching && "animate-spin")} aria-hidden />
          Refresh status
        </Button>
      }
    />
  );

  if (appMode) {
    return (
      <>
        {header}
        <QueryGate query={settings} skeleton={<CardsSkeleton />}>
          {(view) => (
            <div className="space-y-6">
              {!view.ready ? <SetupGuide systems={systems} /> : null}
              <IndexChoice indexType={indexType} />
              <SystemGrid systems={systems} appMode healthError={connections.error} />
              {view.ready ? <SetupCheckCard /> : null}
              {ledger ? <LedgerCard ledger={ledger} /> : null}
              {view.ready ? (
                <Card>
                  <CardHeader title="How RAGGuard connects" />
                  <CardBody>
                    <TrustPoints />
                  </CardBody>
                </Card>
              ) : null}
            </div>
          )}
        </QueryGate>
      </>
    );
  }

  return (
    <>
      {header}
      <div className="space-y-6">
        <EnvNote>The connections below are read-only here. To change them, change the server&apos;s environment.</EnvNote>
        <QueryGate query={connections} skeleton={<CardsSkeleton />}>
          {() => (
            <>
              <SystemGrid systems={systems} appMode={false} />
              <SetupCheckCard />
              {ledger ? <LedgerCard ledger={ledger} /> : null}
            </>
          )}
        </QueryGate>
      </div>
    </>
  );
}
