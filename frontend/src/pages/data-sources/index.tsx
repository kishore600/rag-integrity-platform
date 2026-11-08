import { RefreshCw, Server } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { PageHeader } from "@/components/shared/page";
import { Skeleton } from "@/components/shared/states";
import { cn } from "@/lib/cn";
import type { ConnectionStatus } from "@/types/api";
import { EnvNote, QueryGate, StateBadge, useSystems, type SystemStatus } from "../_settings-form";
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

function SystemGrid({ systems, appMode, healthError }: { systems: SystemStatus[]; appMode: boolean; healthError?: unknown }) {
  const current = appMode ? systems.find((s) => !s.configured)?.kind : undefined;
  return (
    <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
      {systems.map((s, i) => (
        <SystemCard key={s.kind} system={s} appMode={appMode} highlight={current === s.kind} healthError={healthError} className={i === 2 ? "md:col-span-2 xl:col-span-1" : undefined} />
      ))}
    </div>
  );
}

export default function DataSourcesPage() {
  const { appMode, settings, connections, systems, ledger, refresh, fetching } = useSystems();

  const header = (
    <PageHeader
      title="Data sources"
      description="The three systems RAGGuard compares."
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
              <SystemGrid systems={systems} appMode healthError={connections.error} />
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
              {ledger ? <LedgerCard ledger={ledger} /> : null}
            </>
          )}
        </QueryGate>
      </div>
    </>
  );
}
