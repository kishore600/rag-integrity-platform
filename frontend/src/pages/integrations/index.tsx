import { ExternalLink } from "lucide-react";
import { Link } from "react-router-dom";
import { buttonVariants } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { CopyButton } from "@/components/shared/copy-button";
import { LinkButton } from "@/components/shared/link-button";
import { PageHeader, Mono } from "@/components/shared/page";
import { NotAvailable, Skeleton } from "@/components/shared/states";
import { useOverview } from "@/hooks/queries";
import { API_DOCS_URL } from "@/lib/links";
import { EnvNote, QueryGate, StateBadge, useSystems } from "../_settings-form";
import { ApiKeysSection } from "./api-keys";
import { RepairCard } from "./repair-card";

function RestApiCard() {
  const origin = window.location.origin;
  return (
    <Card>
      <CardHeader title="REST API" description="Everything in this interface is also available over HTTP." />
      <CardBody className="space-y-4">
        <div>
          <p className="text-support text-ink-2">Base URL</p>
          <div className="mt-1 flex flex-wrap items-center gap-2">
            <Mono>{origin}</Mono>
            <CopyButton text={origin} label="Copy" />
          </div>
        </div>
        <a href={API_DOCS_URL} target="_blank" rel="noreferrer" className={buttonVariants({ variant: "secondary" })}>
          Open API documentation <ExternalLink className="h-4 w-4" aria-hidden />
          <span className="sr-only">(opens in a new tab)</span>
        </a>
      </CardBody>
    </Card>
  );
}

function ConnectedSystems({ appMode }: { appMode: boolean }) {
  const { settings, systems } = useSystems();
  // each badge says "Checking" or "Status unavailable" by itself while the live health loads; only app mode has to wait for the saved settings
  const list = (
    <ul className="divide-y divide-line">
      {systems.map((s) => {
        const Icon = s.icon;
        return (
          <li key={s.kind} className="flex items-center gap-3 px-5 py-3">
            <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-control bg-surface text-ink-2">
              <Icon className="h-4 w-4" aria-hidden />
            </span>
            <div className="min-w-0 flex-1">
              <p className="text-card text-ink">{s.name}</p>
              <p className="text-support text-ink-2">{s.eyebrow}</p>
            </div>
            <StateBadge state={s.state} />
          </li>
        );
      })}
    </ul>
  );
  return (
    <Card>
      <CardHeader
        title="Connected systems"
        description="The three systems RAGGuard compares."
        actions={<LinkButton to="/data-sources" variant="secondary" size="sm">Manage data sources</LinkButton>}
      />
      {appMode ? (
        <QueryGate query={settings} compact skeleton={<div className="space-y-3 p-5" aria-busy><Skeleton className="h-10" /><Skeleton className="h-10" /><Skeleton className="h-10" /></div>}>
          {() => list}
        </QueryGate>
      ) : (
        list
      )}
    </Card>
  );
}

/** Single-user servers have no per-workspace keys: access is a single shared key from the server's environment, or none. */
function SharedKeyNote({ required }: { required: boolean }) {
  return (
    <Card>
      <CardHeader title="API access" description="Single-user mode has no per-person API keys." />
      <CardBody>
        <EnvNote>
          {required
            ? "This server requires its shared key (RAGI_API_KEY). Send it in the X-API-Key header or as a Bearer token."
            : "No API key is required on this server. Set RAGI_API_KEY to protect it."}
        </EnvNote>
      </CardBody>
    </Card>
  );
}

export default function IntegrationsPage() {
  const { session, appMode, settings } = useSystems();
  const overview = useOverview(!appMode && !!session);
  const repairGroup = settings.data?.kinds.find((k) => k.kind === "repair");

  return (
    <>
      <PageHeader title="Integrations" description="Connect RAGGuard to the rest of your stack." />
      <div className="space-y-6">
        {appMode ? (
          <QueryGate query={settings} skeleton={<Skeleton className="h-96" />}>
            {() => <RepairCard appMode group={repairGroup} />}
          </QueryGate>
        ) : (
          <QueryGate query={overview} skeleton={<Skeleton className="h-96" />}>
            {(o) => <RepairCard appMode={false} singleUser={{ configured: o.repair_webhook_configured, cleanupPolicy: o.cleanup_policy }} />}
          </QueryGate>
        )}

        {appMode ? <ApiKeysSection /> : <SharedKeyNote required={!!session?.api_key_required} />}

        <div className="grid gap-6 lg:grid-cols-2">
          <RestApiCard />
          <ConnectedSystems appMode={appMode} />
        </div>

        <section aria-labelledby="other-integrations">
          <h2 id="other-integrations" className="mb-3 text-section text-ink">Other integrations</h2>
          <div className="grid gap-4 md:grid-cols-3">
            {["Slack", "Jira", "PagerDuty"].map((name) => (
              <NotAvailable
                key={name}
                title={name}
                description={
                  <>
                    To forward findings today, use the alert webhook on the{" "}
                    <Link to="/alerts" className="text-brand hover:underline">Alerts page</Link>.
                  </>
                }
              />
            ))}
          </div>
        </section>
      </div>
    </>
  );
}
