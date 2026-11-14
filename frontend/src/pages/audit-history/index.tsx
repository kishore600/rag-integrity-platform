import { Plug } from "lucide-react";
import { useParams, useSearchParams } from "react-router-dom";
import { Card } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/menus";
import { LinkButton } from "@/components/shared/link-button";
import { PageHeader } from "@/components/shared/page";
import { EmptyState } from "@/components/shared/states";
import { useSession } from "@/hooks/queries";
import { ActivityTab } from "./activity-log";
import { RunDetail } from "./run-detail";
import { RunsTab } from "./runs-table";

type Tab = "runs" | "activity";

/** `/audit-history` lists audits and activity; `/audit-history/:runId` shows one audit. */
export default function AuditHistoryPage() {
  const { runId } = useParams();
  return runId ? <RunDetail runId={runId} /> : <AuditHistoryList />;
}

function AuditHistoryList() {
  const session = useSession().data;
  const needsSetup = !!session && session.app && !session.ready;
  const [params, setParams] = useSearchParams();
  const tab: Tab = params.get("tab") === "activity" ? "activity" : "runs";

  // switching tabs starts that tab's filters from scratch: they belong to the tab, not to the page
  function selectTab(next: string) {
    setParams(next === "activity" ? { tab: "activity" } : {}, { replace: true });
  }

  return (
    <>
      <PageHeader title="Audit history" description="Every audit that has run, and everything that changed in your index because of them." />
      {needsSetup ? (
        <Card>
          <EmptyState
            icon={Plug}
            title="No audits yet"
            description="Connect your S3 source and your vector index, then run your first audit. Every audit is recorded here."
            action={
              <LinkButton variant="primary" to="/data-sources">
                Go to Data Sources
              </LinkButton>
            }
          />
        </Card>
      ) : (
        <Tabs value={tab} onValueChange={selectTab}>
          <TabsList aria-label="Audit history sections">
            <TabsTrigger value="runs">Audit runs</TabsTrigger>
            <TabsTrigger value="activity">Activity log</TabsTrigger>
          </TabsList>
          <TabsContent value="runs">
            <RunsTab />
          </TabsContent>
          <TabsContent value="activity">
            <ActivityTab />
          </TabsContent>
        </Tabs>
      )}
    </>
  );
}
