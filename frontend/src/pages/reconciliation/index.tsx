import { GitCompareArrows, Play, Plug, Target } from "lucide-react";
import { useState, type ReactNode } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Tip } from "@/components/ui/menus";
import { LinkButton } from "@/components/shared/link-button";
import { PageHeader } from "@/components/shared/page";
import { EmptyState, ErrorState, Skeleton } from "@/components/shared/states";
import { useOverview, useSession } from "@/hooks/queries";
import { useRunAudit } from "@/hooks/use-run-audit";
import { AuditProgressCard } from "./audit-progress";
import { ThreeWayCard } from "./comparison";
import { DocumentsCard } from "./documents-card";
import { ExportMenu } from "./export-menu";
import { ResultsCard } from "./results";
import { ScopedAuditModal } from "./scoped-audit";

export default function ReconciliationPage() {
  const session = useSession().data;
  // multi-user workspace that has not connected its three systems yet: there is nothing to compare
  const needsSetup = !!session && session.app && !session.ready;
  const overview = useOverview(!needsSetup);
  const audit = useRunAudit();
  const [scopedOpen, setScopedOpen] = useState(false);

  const o = overview.data;
  const tenants = o?.documents.tenants ?? [];
  const full = o?.latest_full_run ?? null;
  const blocked = !!audit.disabledReason && !audit.running;

  const gate = (button: ReactNode, reason: string | null) =>
    reason ? (
      <Tip content={reason}>
        <span tabIndex={0} className="inline-flex rounded-control">
          {button}
        </span>
      </Tip>
    ) : (
      button
    );

  const fullAuditButton = (variant: "primary" | "secondary" = "primary") =>
    gate(
      <Button variant={variant} onClick={() => audit.run({})} loading={audit.running} disabled={blocked}>
        {!audit.running ? <Play className="h-4 w-4" aria-hidden /> : null}
        {audit.running ? "Audit running" : "Run full audit"}
      </Button>,
      blocked ? audit.disabledReason : null,
    );

  const exportReason = overview.isError || o?.latest_run ? null : o ? "Run an audit first to create a report" : "Loading the latest audit";

  const header = (
    <PageHeader
      title="Reconciliation"
      description="Compare your source documents with your vector index, and with your manifest if you connected one."
      actions={
        <>
          {needsSetup ? null : <ExportMenu disabledReason={exportReason} />}
          {gate(
            <Button variant="secondary" onClick={() => setScopedOpen(true)} disabled={!!audit.disabledReason}>
              <Target className="h-4 w-4" aria-hidden /> Scoped audit
            </Button>,
            audit.disabledReason,
          )}
          {fullAuditButton()}
        </>
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
            description="Reconciliation compares your S3 documents with your vector index (and your manifest, if you connect one). Connect your source and your index to run your first audit."
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
      <div className="space-y-6">
        {o?.audit_running ? <AuditProgressCard run={o.latest_run} /> : null}

        {overview.isPending ? (
          <ComparisonSkeleton />
        ) : overview.isError ? (
          <Card>
            <ErrorState error={overview.error} onRetry={() => void overview.refetch()} />
          </Card>
        ) : full ? (
          <>
            <ThreeWayCard run={full} />
            <ResultsCard run={full} />
          </>
        ) : (
          <Card>
            <EmptyState
              icon={GitCompareArrows}
              title="No full audit has finished yet"
              description="Run a full audit to count what your source and your index each hold (and your manifest, if you connected one) and to list every difference."
              action={fullAuditButton()}
            />
          </Card>
        )}

        {o && !o.latest_run ? null : <DocumentsCard tenants={tenants} />}
      </div>

      <ScopedAuditModal open={scopedOpen} onOpenChange={setScopedOpen} tenants={tenants} onRun={(req) => audit.run(req)} />
    </>
  );
}

function ComparisonSkeleton() {
  return (
    <Card aria-busy aria-label="Loading comparison">
      <CardHeader title="Three-way comparison" description="What each system holds, as counted by the latest full audit." />
      <CardBody>
        <div className="grid gap-3 md:grid-cols-3">
          {[0, 1, 2].map((i) => (
            <Skeleton key={i} className="h-[116px] w-full" />
          ))}
        </div>
        <Skeleton className="mt-5 h-4 w-2/3" />
      </CardBody>
    </Card>
  );
}
