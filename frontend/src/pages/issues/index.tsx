import { Database } from "lucide-react";
import { useNavigate, useLocation, useParams } from "react-router-dom";
import { Card } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/menus";
import { LinkButton } from "@/components/shared/link-button";
import { PageHeader } from "@/components/shared/page";
import { EmptyState } from "@/components/shared/states";
import { useSession } from "@/hooks/queries";
import { ImpactTab } from "./impact-tab";
import { IssueDrawer } from "./issue-drawer";
import { IssuesTab } from "./issues-tab";
import { PlansTab } from "./plans-tab";
import { oneOf, useParamState } from "./url-state";

const VIEWS = ["issues", "plans", "impact"] as const;

/** `/issues` and `/issues/:issueId`: the list stays on screen and the issue opens in a drawer on top of it. */
export default function IssuesPage() {
  const session = useSession().data;
  const connected = session ? (session.app ? !!session.ready : true) : false;
  const { params, set } = useParamState();
  const { issueId } = useParams();
  const navigate = useNavigate();
  const location = useLocation();
  const view = oneOf(params.get("view"), VIEWS, "issues");

  const closeIssue = () => navigate({ pathname: "/issues", search: location.search });

  return (
    <>
      <PageHeader title="Integrity issues" description="Everything that makes your index disagree with your source." />

      {!connected ? (
        <Card>
          <EmptyState
            icon={Database}
            title="Connect your data sources first"
            description="RAGGuard needs your S3 source and your vector index before it can find integrity issues."
            action={<LinkButton variant="primary" to="/data-sources">Go to Data Sources</LinkButton>}
          />
        </Card>
      ) : (
        <Tabs value={view} onValueChange={(v) => set({ view: v === "issues" ? null : v, plan: null }, { replace: false })}>
          <TabsList aria-label="Issue views">
            <TabsTrigger value="issues">Issues</TabsTrigger>
            <TabsTrigger value="plans">Repair plans</TabsTrigger>
            <TabsTrigger value="impact">Impact analysis</TabsTrigger>
          </TabsList>
          <TabsContent value="issues">
            <IssuesTab activeIssueId={issueId} />
          </TabsContent>
          <TabsContent value="plans">
            <PlansTab />
          </TabsContent>
          <TabsContent value="impact">
            <ImpactTab />
          </TabsContent>
        </Tabs>
      )}

      {connected && issueId ? <IssueDrawer key={issueId} id={issueId} onClose={closeIssue} /> : null}
    </>
  );
}
