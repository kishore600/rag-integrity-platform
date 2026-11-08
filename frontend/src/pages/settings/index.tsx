import { useSearchParams } from "react-router-dom";
import { PageHeader } from "@/components/shared/page";
import { NotAvailable, Skeleton } from "@/components/shared/states";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/menus";
import { useSession, useSettings } from "@/hooks/queries";
import { GeneralTab } from "./general";
import { PipelineTab, PolicyTab } from "./pipeline-policy";
import { SecurityTab } from "./security";

const TABS = [
  { value: "general", label: "General" },
  { value: "pipeline", label: "Pipeline" },
  { value: "policy", label: "Policy" },
  { value: "security", label: "Security" },
  { value: "team", label: "Team" },
  { value: "billing", label: "Billing" },
] as const;

export default function SettingsPage() {
  const session = useSession().data;
  const appMode = !!session?.app;
  // /api/settings only exists in app mode
  const settings = useSettings(appMode);
  const [params, setParams] = useSearchParams();
  const requested = params.get("tab");
  const tab = TABS.find((t) => t.value === requested)?.value ?? "general";

  function changeTab(value: string) {
    const next = new URLSearchParams(params);
    next.set("tab", value);
    setParams(next, { replace: true });
  }

  return (
    <>
      <PageHeader title="Settings" description="Your workspace, the pipeline you expect, and your account." />
      {!session ? (
        <Skeleton className="h-64" />
      ) : (
        <Tabs value={tab} onValueChange={changeTab}>
          <TabsList aria-label="Settings sections">
            {TABS.map((t) => (
              <TabsTrigger key={t.value} value={t.value}>{t.label}</TabsTrigger>
            ))}
          </TabsList>
          <TabsContent value="general">
            <GeneralTab session={session} />
          </TabsContent>
          <TabsContent value="pipeline">
            <PipelineTab appMode={appMode} settings={settings} />
          </TabsContent>
          <TabsContent value="policy">
            <PolicyTab appMode={appMode} settings={settings} />
          </TabsContent>
          <TabsContent value="security">
            <SecurityTab session={session} />
          </TabsContent>
          <TabsContent value="team">
            <NotAvailable title="Invite teammates and set roles" description="Each account owns one workspace today. Sharing a workspace and giving people roles is not available yet." />
          </TabsContent>
          <TabsContent value="billing">
            <NotAvailable title="Plans and invoices" description="RAGGuard has no plans or invoicing yet." />
          </TabsContent>
        </Tabs>
      )}
    </>
  );
}
