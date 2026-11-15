import { CircleAlert, CircleCheck, Mail } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { errorMessage } from "@/lib/api";
import { useSendTestEmail } from "@/hooks/queries";
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

/** Sends one real message through the operator's mail account, so setup can be checked without waiting for an audit. */
function TestEmailCard() {
  const send = useSendTestEmail();
  const r = send.data;
  return (
    <Card>
      <CardHeader title="Send a test email" description="Checks that the mail account works, without waiting for an audit." />
      <CardBody className="space-y-3">
        <p className="text-body text-ink-2">Sends one short message to the address you sign in with. It changes nothing, and you can send at most five every ten minutes.</p>
        <Button variant="secondary" loading={send.isPending} onClick={() => send.mutate()}>
          <Mail className="h-4 w-4" aria-hidden /> Send test email
        </Button>
        <div aria-live="polite">
          {r?.ok ? (
            <p className="flex items-start gap-2 text-body text-ink" role="status">
              <CircleCheck className="mt-0.5 h-4 w-4 shrink-0 text-success" aria-hidden />
              <span className="min-w-0 break-words">Sent to {r.to.join(", ")}. Check your inbox, and the spam folder if it is not there within a minute.</span>
            </p>
          ) : r ? (
            <p className="flex items-start gap-2 text-body text-ink" role="alert">
              <CircleAlert className="mt-0.5 h-4 w-4 shrink-0 text-critical" aria-hidden />
              <span className="min-w-0 break-words">Not sent. {r.reason ?? "The mail server did not accept it."}</span>
            </p>
          ) : null}
          {send.isError ? (
            <p className="flex items-start gap-2 text-body text-ink" role="alert">
              <CircleAlert className="mt-0.5 h-4 w-4 shrink-0 text-critical" aria-hidden />
              <span className="min-w-0 break-words">Not sent. {errorMessage(send.error)}</span>
            </p>
          ) : null}
        </div>
      </CardBody>
    </Card>
  );
}

function HowAlertsWork() {
  const items: { title: string; body: React.ReactNode }[] = [
    {
      title: "In the app and by email",
      body: "After every audit that finishes (completed, stopped part-way or failed), RAGGuard adds a notification under the bell and, unless email is switched off, emails it to the people in your workspace. Each one carries the next step: Resume audit, Run it again, Review the issues, Verify deletions. In the email, a step that changes something opens the Notifications page, where its button is.",
    },
    { title: "When the Slack webhook runs", body: "After every audit that finishes, RAGGuard compares the issues it found with the previous results." },
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
    { title: "When nothing is sent", body: "If no webhook is saved, or no issue qualifies, nothing is sent to it. An email needs the operator's mail server to be set up; if it is not, or email is off, the reason is recorded on the run. At most 12 emails an hour are sent per workspace." },
  ];
  return (
    <Card className="min-w-0">
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
          <div className="min-w-0 space-y-6">
          {appMode ? (
            <QueryGate query={settings} skeleton={<Skeleton className="h-80" />}>
              {() =>
                group ? (
                  <Card>
                    <CardHeader
                      title="Email and webhook"
                      description="Choose when you get the email. The optional Slack-compatible webhook is saved encrypted and never shown again."
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
              <CardHeader title="Email and webhook" description="Set in the server's environment." />
              <CardBody>
                <EnvNote>
                  For email set RAGI_SMTP_HOST, RAGI_SMTP_FROM (and RAGI_SMTP_USER, RAGI_SMTP_PASSWORD if the server needs a login), RAGI_ALERT_EMAIL_TO for who gets it, and RAGI_ALERT_EMAIL_WHEN (always, attention or never). For Slack set RAGI_ALERT_WEBHOOK_URL, and RAGI_ALERT_MIN_SEVERITY to choose the minimum severity.
                </EnvNote>
              </CardBody>
            </Card>
          )}
          <TestEmailCard />
          </div>
          <HowAlertsWork />
        </div>

        <RecentDeliveries />

        <section aria-labelledby="more-alerts">
          <h2 id="more-alerts" className="mb-3 text-section text-ink">More ways to be notified</h2>
          <div className="grid gap-4 md:grid-cols-2">
            <NotAvailable title="Per-issue-type rules" description="The only filter is the minimum severity." />
            <NotAvailable title="Digest and quiet hours" description="An alert is sent right after each audit that finds something new." />
          </div>
        </section>
      </div>
    </>
  );
}
