import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Mono, PageHeader } from "@/components/shared/page";
import { NotAvailable, Skeleton } from "@/components/shared/states";
import { CodeBlock, ConfigBadge, EnvNote, QueryGate, SettingsForm, useSystems } from "../_settings-form";
import { RecentDeliveries } from "./deliveries";

const PAYLOAD_SHAPE = `{
  "text": "<short summary for Slack>",
  "run_id": "<audit run id>",
  "summary": { "new_issues": <number>, "health_score": <number> },
  "issues": [
    { "id": "...", "type": "...", "severity": "...", "tenant_id": "...", "document_id": "...", "title": "..." }
  ]
}`;

function HowAlertsWork() {
  const items: { title: string; body: React.ReactNode }[] = [
    { title: "When it runs", body: "After every audit that finishes, RAGGuard compares the issues it found with the previous results." },
    {
      title: "What triggers an alert",
      body: "Only issues that are new, reopened (they came back after being resolved) or escalated (their severity went up), and only if they are at or above the minimum severity. An issue that is still open and unchanged never alerts again.",
    },
    {
      title: "What is sent",
      body: (
        <>
          One JSON request to your webhook. <Mono>text</Mono> is a readable summary for Slack: the count, the minimum severity, the health score and up to 10 issues. The same request carries <Mono>run_id</Mono>, a <Mono>summary</Mono> and an <Mono>issues</Mono> list of up to 25 issues.
        </>
      ),
    },
    {
      title: "If delivery fails",
      body: "RAGGuard makes one attempt and waits up to 10 seconds. It does not retry. A failed delivery never fails the audit: the error is recorded on the run and listed under Recent deliveries.",
    },
    { title: "When nothing is sent", body: "If no webhook is saved, or no issue qualifies, nothing is sent. The reason is recorded on the run." },
  ];
  return (
    <Card>
      <CardHeader title="How alerts work" />
      <CardBody className="space-y-4">
        <ol className="space-y-3">
          {items.map((i, n) => (
            <li key={i.title} className="flex gap-3">
              <span className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-brand-light text-support font-semibold text-brand" aria-hidden>{n + 1}</span>
              <div className="min-w-0">
                <h3 className="text-card text-ink">{i.title}</h3>
                <p className="mt-0.5 text-body text-ink-2">{i.body}</p>
              </div>
            </li>
          ))}
        </ol>
        <CodeBlock label="Request body, by shape" code={PAYLOAD_SHAPE} />
      </CardBody>
    </Card>
  );
}

export default function AlertsPage() {
  const { appMode, settings } = useSystems();
  const group = settings.data?.kinds.find((k) => k.kind === "alerts");

  return (
    <>
      <PageHeader title="Alerts" description="Get told when an audit finds something new." />
      <div className="space-y-6">
        <div className="grid items-start gap-6 xl:grid-cols-[minmax(0,5fr)_minmax(0,6fr)]">
          {appMode ? (
            <QueryGate query={settings} skeleton={<Skeleton className="h-80" />}>
              {() =>
                group ? (
                  <Card>
                    <CardHeader
                      title="Alert webhook"
                      description="A Slack-compatible incoming webhook. It is saved encrypted and never shown again."
                      actions={<ConfigBadge configured={group.configured} />}
                    />
                    <CardBody>
                      <SettingsForm
                        group={group}
                        testLabel="Check settings"
                        testNote="Checks that the values are valid and the address is allowed. It does not send a message."
                      />
                    </CardBody>
                  </Card>
                ) : null
              }
            </QueryGate>
          ) : (
            <Card>
              <CardHeader title="Alert webhook" description="A Slack-compatible incoming webhook." />
              <CardBody>
                <EnvNote>Set RAGI_ALERT_WEBHOOK_URL to turn alerts on, and RAGI_ALERT_MIN_SEVERITY to choose the minimum severity.</EnvNote>
              </CardBody>
            </Card>
          )}
          <HowAlertsWork />
        </div>

        <RecentDeliveries />

        <section aria-labelledby="more-alerts">
          <h2 id="more-alerts" className="mb-3 text-section text-ink">More ways to be notified</h2>
          <div className="grid gap-4 md:grid-cols-3">
            <NotAvailable title="Email alerts" description="Alerts go to a webhook only." />
            <NotAvailable title="Per-issue-type rules" description="The only filter is the minimum severity." />
            <NotAvailable title="Digest and quiet hours" description="An alert is sent right after each audit that finds something new." />
          </div>
        </section>
      </div>
    </>
  );
}
