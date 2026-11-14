import { Lock, Plug } from "lucide-react";
import { useState } from "react";
import { Card } from "@/components/ui/card";
import { LinkButton } from "@/components/shared/link-button";
import { PageHeader } from "@/components/shared/page";
import { EmptyState, ErrorState, Skeleton } from "@/components/shared/states";
import { useIsolation, useIsolationDrill, useSession } from "@/hooks/queries";
import type { IsolationAvailable } from "@/types/api";
import { StatusBanner } from "./banner";
import { ChecksCard, ChecksSkeleton } from "./checks-card";
import { DrillDialog } from "./drill-dialog";
import { DrillButton, HowToReadCard, LimitedCard, SingleTenantCard } from "./explain";
import { FindingsCard } from "./findings-card";
import { IsolationKpis, IsolationKpisSkeleton } from "./kpis";
import { ReportButton } from "./report-button";
import { RunFullAuditButton } from "./run-audit-button";
import { TenantsCard, TenantsSkeleton } from "./tenants-card";

export default function IsolationPage() {
  const session = useSession().data;
  const appMode = !!session?.app;
  // multi-user workspace that has not connected its three systems yet: there is nothing to check
  const needsSetup = !!session && session.app && !session.ready;

  const q = useIsolation(!needsSetup);
  const drill = useIsolationDrill();
  const [drillOpen, setDrillOpen] = useState(false);

  // The drill starts the moment the dialog opens. Closing it forgets the result, so the next open starts clean.
  function startDrill() {
    setDrillOpen(true);
    drill.mutate({});
  }
  function changeDrillOpen(open: boolean) {
    setDrillOpen(open);
    if (!open) drill.reset();
  }

  const available: IsolationAvailable | null = q.data?.available ? q.data : null;
  const status = available?.overall.status;
  // in these two states the explanation card carries the main drill button, so the header one steps back
  const explained = status === "limited" || status === "not_applicable";

  const reportReason = q.isPending ? "Loading the latest result" : q.isError ? "The result could not be loaded" : !available ? "Run a full audit first to create a report" : null;

  const header = (
    <PageHeader
      title="Isolation"
      description="Tenant isolation means one customer's content never shows up for another customer. This page shows whether your index keeps tenants apart."
      actions={
        needsSetup ? null : (
          <>
            <ReportButton disabledReason={reportReason} />
            <DrillButton onClick={startDrill} variant={available && !explained ? "primary" : "secondary"} />
          </>
        )
      }
    />
  );

  if (needsSetup) {
    return (
      <>
        {header}
        <Card>
          <EmptyState
            icon={Plug}
            title="Connect your data first"
            description="Isolation is checked from a full audit of your S3 documents and your vector index. Connect both, then run your first audit."
            action={
              <LinkButton variant="primary" to="/data-sources">
                Go to Data Sources
              </LinkButton>
            }
          />
        </Card>
      </>
    );
  }

  return (
    <>
      {header}
      {q.isPending ? (
        <LoadingSkeleton />
      ) : q.isError ? (
        <Card>
          <ErrorState error={q.error} onRetry={() => void q.refetch()} />
        </Card>
      ) : q.data.available ? (
        <div className="space-y-6">
          <StatusBanner data={q.data} />
          {q.data.overall.status === "limited" ? <LimitedCard appMode={appMode} onDrill={startDrill} /> : null}
          {q.data.overall.status === "not_applicable" ? <SingleTenantCard onDrill={startDrill} /> : null}
          <IsolationKpis o={q.data.overall} />
          <ChecksCard checks={q.data.checks} overall={q.data.overall.status} />
          <TenantsCard tenants={q.data.tenants} total={q.data.tenants_total} limited={q.data.overall.status === "limited"} />
          <FindingsCard
            findings={q.data.findings}
            total={q.data.findings_total}
            limited={q.data.overall.status === "limited"}
            changedSinceAudit={q.data.findings_changed_since_audit}
          />
          <HowToReadCard />
        </div>
      ) : (
        <div className="space-y-6">
          <Card>
            <EmptyState
              icon={Lock}
              title="No isolation result yet"
              description={
                <>
                  {q.data.note}
                  <span className="mt-2 block">You can still run the isolation drill, with the button at the top of this page, to see how RAGGuard reacts when a document is indexed under the wrong tenant.</span>
                </>
              }
              action={<RunFullAuditButton />}
            />
          </Card>
          <HowToReadCard />
        </div>
      )}
      <DrillDialog open={drillOpen} onOpenChange={changeDrillOpen} drill={drill} onRun={startDrill} />
    </>
  );
}

/** The same blocks as the loaded page, so nothing moves when the result arrives. */
function LoadingSkeleton() {
  return (
    <div className="space-y-6" aria-busy aria-label="Loading the isolation result">
      <Skeleton className="h-[100px] w-full rounded-card" />
      <IsolationKpisSkeleton />
      <ChecksSkeleton />
      <TenantsSkeleton />
      <Skeleton className="h-48 w-full rounded-card" />
    </div>
  );
}
