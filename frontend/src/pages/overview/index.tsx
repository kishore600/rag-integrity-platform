import { FileText, HeartPulse, History, SearchCheck, TriangleAlert } from "lucide-react";
import type { ReactNode } from "react";
import { useNavigate } from "react-router-dom";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { EmptyState, ErrorState, Skeleton } from "@/components/shared/states";
import { KpiCard, PageHeader } from "@/components/shared/page";
import { RunWarningsNotice, runWarnings } from "@/components/shared/run-warnings";
import { healthTone } from "@/components/shared/status";
import { useOverview, useSession } from "@/hooks/queries";
import { formatDuration, formatNumber, formatPercent, timeAgo } from "@/lib/format";
import { links } from "@/lib/links";
import type { Overview } from "@/types/api";
import { DocumentStatusCard, IssuesByTypeCard } from "./breakdowns";
import { HealthTrendCard, SeverityCard } from "./charts";
import { ConnectionHealthCard, LastAuditCard, TenantHealthCard, TopIssuesCard } from "./lists";
import { OnboardingCard } from "./onboarding";
import { Banner, RunAuditButton, capitalize } from "./ui";

export default function OverviewPage() {
  const session = useSession().data;
  // multi-user workspace that has not connected its three systems yet: nothing to show but the next step
  const needsSetup = !!session && session.app && !session.ready;

  return (
    <>
      <PageHeader title="Overview" description="How healthy your RAG index is right now." />
      {needsSetup ? <OnboardingCard /> : <OverviewBody />}
    </>
  );
}

function OverviewBody() {
  const q = useOverview();
  if (q.isPending) return <OverviewSkeleton />;
  if (q.isError) {
    return (
      <Card>
        <ErrorState error={q.error} onRetry={() => void q.refetch()} />
      </Card>
    );
  }
  return <Dashboard o={q.data} />;
}

function Dashboard({ o }: { o: Overview }) {
  const navigate = useNavigate();
  const run = o.latest_run;

  const banner = o.audit_running ? <Banner>An audit is running. This page updates when it finishes.</Banner> : null;

  if (!run) {
    return (
      <div className="space-y-6">
        {banner}
        <Card>
          <EmptyState
            icon={SearchCheck}
            title="No audit has run yet"
            description="Run your first audit to compare your source documents, your manifest and your vector index."
            action={<RunAuditButton label="Run first audit" />}
          />
        </Card>
        <ConnectionHealthCard />
      </div>
    );
  }

  const sev = o.issues.by_severity;
  const urgent = (sev.critical ?? 0) + (sev.high ?? 0);
  const score = o.documents.health_score;
  const tenants = o.documents.tenants;
  const duration = run.stats.duration_seconds;
  const showTypes = Object.values(o.issues.by_type).some((n) => n > 0);
  const showStatus = o.documents.total > 0;
  const hasLeft = o.issues.open > 0 || tenants.length > 0;
  const idWarnings = runWarnings(o.latest_full_run?.stats);

  const right = [<LastAuditCard key="audit" run={run} />, <ConnectionHealthCard key="connections" />];

  return (
    <div className="space-y-6">
      {banner}

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <KpiCard
          label="Health score"
          icon={HeartPulse}
          tone={healthTone(score)}
          value={formatPercent(score)}
          hint={score === null ? "No documents audited yet" : "of documents are healthy"}
        />
        <KpiCard
          label="Documents"
          icon={FileText}
          tone="brand"
          value={formatNumber(o.documents.total)}
          hint={`across ${formatNumber(tenants.length)} ${tenants.length === 1 ? "tenant" : "tenants"}`}
        />
        <KpiCard
          label="Open issues"
          icon={TriangleAlert}
          tone={o.issues.open === 0 ? "success" : urgent > 0 ? "critical" : "warning"}
          value={formatNumber(o.issues.open)}
          hint={urgent === 0 ? "None critical or high" : `${formatNumber(urgent)} critical or high`}
          onClick={() => navigate(links.issues())}
        />
        <KpiCard
          label="Last audit"
          icon={History}
          tone={run.status === "failed" ? "critical" : run.status === "running" ? "info" : "brand"}
          value={timeAgo(run.finished_at ?? run.started_at)}
          hint={run.status === "running" ? "Running now" : `${capitalize(run.status)}${duration !== undefined ? ` in ${formatDuration(duration)}` : ""}`}
          onClick={() => navigate(links.audit(run.id))}
        />
      </div>

      {idWarnings.length > 0 && o.latest_full_run ? <RunWarningsNotice warnings={idWarnings} runId={o.latest_full_run.id} /> : null}

      <div className="grid gap-4 lg:grid-cols-3">
        <HealthTrendCard trend={o.trend} />
        <SeverityCard bySeverity={sev} open={o.issues.open} />
      </div>

      {showTypes || showStatus ? (
        <div className="grid gap-4 lg:grid-cols-2">
          {showTypes ? <IssuesByTypeCard byType={o.issues.by_type} className={showStatus ? undefined : "lg:col-span-2"} /> : null}
          {showStatus ? <DocumentStatusCard byStatus={o.documents.by_status} total={o.documents.total} className={showTypes ? undefined : "lg:col-span-2"} /> : null}
        </div>
      ) : null}

      {hasLeft ? (
        <div className="grid items-start gap-4 lg:grid-cols-3">
          <div className="min-w-0 space-y-4 lg:col-span-2">
            {o.issues.open > 0 ? <TopIssuesCard /> : null}
            {tenants.length > 0 ? <TenantHealthCard tenants={tenants} /> : null}
          </div>
          <div className="min-w-0 space-y-4">{right}</div>
        </div>
      ) : (
        <div className="grid items-start gap-4 lg:grid-cols-2">{right}</div>
      )}
    </div>
  );
}

// ---- loading: the same layout, so nothing moves when the data arrives ---------------------------------------
function CardSkeleton({ title, description, children, className }: { title: string; description?: string; children: ReactNode; className?: string }) {
  return (
    <Card className={className}>
      <CardHeader title={title} description={description} />
      <CardBody>{children}</CardBody>
    </Card>
  );
}

function RowsSkeleton({ rows }: { rows: number }) {
  return (
    <div className="space-y-4">
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="flex items-center gap-3">
          <Skeleton className="h-4 w-1/4" />
          <Skeleton className="h-2 flex-1" />
          <Skeleton className="h-4 w-8" />
        </div>
      ))}
    </div>
  );
}

function OverviewSkeleton() {
  return (
    <div className="space-y-6" aria-busy aria-label="Loading overview">
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <KpiCard loading label="Health score" icon={HeartPulse} value="" hint=" " />
        <KpiCard loading label="Documents" icon={FileText} value="" hint=" " />
        <KpiCard loading label="Open issues" icon={TriangleAlert} value="" hint=" " />
        <KpiCard loading label="Last audit" icon={History} value="" hint=" " />
      </div>
      <div className="grid gap-4 lg:grid-cols-3">
        <CardSkeleton className="lg:col-span-2" title="Health over time" description="Share of documents that are healthy after each full audit.">
          <Skeleton className="h-[300px] w-full" />
        </CardSkeleton>
        <CardSkeleton title="Open issues by severity" description="Issues that are still open right now.">
          <Skeleton className="h-[300px] w-full" />
        </CardSkeleton>
      </div>
      <div className="grid gap-4 lg:grid-cols-2">
        <CardSkeleton title="Issues by type" description="What is wrong, across all open issues.">
          <RowsSkeleton rows={5} />
        </CardSkeleton>
        <CardSkeleton title="Document status" description="Where every document stands after the last audit.">
          <RowsSkeleton rows={5} />
        </CardSkeleton>
      </div>
      <div className="grid items-start gap-4 lg:grid-cols-3">
        <div className="min-w-0 space-y-4 lg:col-span-2">
          <CardSkeleton title="Top open issues" description="Most serious first, then most recently seen.">
            <RowsSkeleton rows={6} />
          </CardSkeleton>
        </div>
        <div className="min-w-0 space-y-4">
          <CardSkeleton title="Last audit">
            <RowsSkeleton rows={4} />
          </CardSkeleton>
        </div>
      </div>
    </div>
  );
}
