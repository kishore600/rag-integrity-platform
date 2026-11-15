import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import type { SettingsGroup } from "@/types/api";
import { ConfigBadge, EnvNote, SavedStatus, SettingsModal } from "../_settings-form";

const CONTAINS = [
  "A readable summary and a table of the documents, with what to do for each one.",
  "A CSV with every document. It opens in Excel and Google Sheets.",
  "The exact JSON your repair worker would receive (you can leave it out).",
  "A link back to the plan, so the person fixing it can press Verify now afterwards.",
];

const field = (g: SettingsGroup | undefined, name: string) => g?.fields.find((f) => f.name === name);

/**
 * Where RAGGuard sends a repair plan by email. It speaks plain SMTP to your own mail server (or an email provider's relay) and
 * only ever sends when a person presses Email plan and types the recipients.
 */
export function EmailCard({ appMode, group, configured }: { appMode: boolean; group?: SettingsGroup; configured?: boolean }) {
  const [open, setOpen] = useState(false);
  const isConfigured = appMode ? !!group?.configured : !!configured;
  const host = field(group, "host")?.value;
  const port = field(group, "port")?.value;
  const from = field(group, "from_address")?.value;
  const signedIn = !!field(group, "password")?.has_value;

  return (
    <Card>
      <CardHeader
        title="Email"
        description="Send a repair plan to the people who will fix it. Nothing is sent unless someone presses Email plan and types the recipients."
        actions={
          <>
            <ConfigBadge configured={isConfigured} />
            {appMode && group ? <Button variant={isConfigured ? "secondary" : "primary"} onClick={() => setOpen(true)}>{group.updated_at ? "Edit" : "Configure"}</Button> : null}
          </>
        }
      />
      <CardBody className="space-y-5">
        {!appMode ? (
          <EnvNote>Plans are sent through the same mail account as the audit alerts. Set RAGI_SMTP_HOST and RAGI_SMTP_FROM (and RAGI_SMTP_PORT, RAGI_SMTP_SECURITY, RAGI_SMTP_USER, RAGI_SMTP_PASSWORD as your mail server needs) in the server&apos;s environment.</EnvNote>
        ) : (
          <dl className="grid gap-x-6 gap-y-3 sm:grid-cols-3">
            <div className="min-w-0">
              <dt className="text-support text-ink-2">Mail server</dt>
              <dd className="mt-0.5 break-all text-body text-ink">{host ? `${String(host)}${port ? `:${String(port)}` : ""}` : "Not set"}</dd>
            </div>
            <div className="min-w-0">
              <dt className="text-support text-ink-2">From address</dt>
              <dd className="mt-0.5 break-all text-body text-ink">{from ? String(from) : "Not set"}</dd>
            </div>
            <div>
              <dt className="text-support text-ink-2">Password</dt>
              <dd className={`mt-0.5 text-body ${signedIn ? "text-success" : "text-ink"}`}>{signedIn ? "Saved" : "Not set"}</dd>
            </div>
          </dl>
        )}

        <div>
          <h3 className="text-card text-ink">What the email contains</h3>
          <ul className="mt-2 list-disc space-y-1.5 pl-5 text-body text-ink-2 marker:text-ink-3">
            {CONTAINS.map((c) => (
              <li key={c}>{c}</li>
            ))}
          </ul>
          <p className="mt-3 text-support text-ink-2">
            Use your own mail server or your provider&apos;s SMTP relay (Gmail, Outlook, SendGrid, Amazon SES and others). For Gmail and similar, create an app password instead of using your normal one.
          </p>
        </div>

        {appMode && group ? <SavedStatus group={group} showTest={false} /> : null}
      </CardBody>
      {appMode && group ? (
        <SettingsModal
          group={group}
          open={open}
          onOpenChange={setOpen}
          title="Email"
          testLabel="Check settings"
          testNote="Connects to your mail server, encrypts the connection and signs in. It does not send any email."
        />
      ) : null}
    </Card>
  );
}
