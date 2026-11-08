import { AlertTriangle } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Mono } from "@/components/shared/page";
import type { SettingsGroup } from "@/types/api";
import { CodeBlock, ConfigBadge, EnvNote, SavedStatus, SettingsModal } from "../_settings-form";

const STEPS = [
  "When you trigger a repair plan, RAGGuard signs a request with HMAC-SHA256 using the shared signing secret and sends it to your webhook URL.",
  "Your worker checks the signature, re-reads the latest source documents, then parses, chunks and embeds them and updates your index and manifest. RAGGuard does none of the writing.",
  "Your worker answers right away and works in the background. When it finishes it can call RAGGuard back, signed the same way. Otherwise an operator clicks Verify.",
  "RAGGuard checks the real index again. Documents that pass are marked as fixed. Documents that do not pass stay in the plan so they can be sent again.",
  "Old vectors are removed only after a document passes verification and an operator approves, unless vector removal is set to auto. Removal is a second signed request that lists the exact point ids.",
];

const VERIFY_SNIPPET = `import hmac, hashlib, time

def verify(secret, timestamp, signature, raw_body: bytes) -> bool:
    if abs(time.time() - float(timestamp)) > 300:  # reject anything older than about 5 minutes
        return False
    mac = hmac.new(secret.encode(), timestamp.encode() + b"." + raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest("sha256=" + mac, signature)`;

const HEADERS: { name: string; value: string }[] = [
  { name: "X-Ragi-Event", value: "repair.requested for the re-index request, cleanup.requested for the removal request." },
  { name: "X-Ragi-Timestamp", value: "Unix time in seconds when the request was signed." },
  { name: "X-Ragi-Signature", value: "sha256= followed by the hex HMAC-SHA256 of the timestamp, a dot and the raw request body, using your signing secret." },
  { name: "X-Ragi-Delivery", value: "A unique id for this delivery. Use it to ignore repeats." },
];

const field = (g: SettingsGroup | undefined, name: string) => g?.fields.find((f) => f.name === name);

function WebhookDetails() {
  return (
    <details className="group rounded-control border border-line">
      <summary className="cursor-pointer select-none px-4 py-3 text-card text-ink hover:bg-surface-hover">What your worker receives</summary>
      <div className="space-y-5 border-t border-line px-4 py-4">
        <div>
          <h4 className="text-card text-ink">Headers</h4>
          <dl className="mt-2 space-y-2">
            {HEADERS.map((h) => (
              <div key={h.name} className="grid gap-1 sm:grid-cols-[180px_minmax(0,1fr)] sm:gap-3">
                <dt><Mono>{h.name}</Mono></dt>
                <dd className="text-support text-ink-2">{h.value}</dd>
              </div>
            ))}
          </dl>
        </div>
        <div>
          <h4 className="text-card text-ink">Re-index request body</h4>
          <p className="mt-1 text-support text-ink-2">
            JSON with <Mono>event</Mono>, <Mono>phase</Mono>, <Mono>plan_id</Mono>, <Mono>created_at</Mono>, <Mono>callback_url</Mono>, <Mono>safety</Mono> and <Mono>target_fingerprint</Mono>, plus an <Mono>items</Mono> list.
            Each item has <Mono>tenant_id</Mono>, <Mono>document_id</Mono>, <Mono>source_uri</Mono>, <Mono>source_version</Mono>, <Mono>source_hash</Mono>, <Mono>expected_chunk_count</Mono>, <Mono>actions</Mono>, <Mono>missing_chunks</Mono> and <Mono>issue_ids</Mono>.
            Write vectors with deterministic ids so a retry replaces them instead of duplicating them. Do not delete anything in this phase.
          </p>
        </div>
        <div>
          <h4 className="text-card text-ink">Removal request body</h4>
          <p className="mt-1 text-support text-ink-2">
            Sent only after verification and approval. It has <Mono>event</Mono>, <Mono>phase</Mono>, <Mono>plan_id</Mono> and a <Mono>cleanup</Mono> list. Each entry has <Mono>tenant_id</Mono>, <Mono>document_id</Mono>, <Mono>collection</Mono>, <Mono>reason</Mono> and the exact <Mono>point_ids</Mono> to delete.
          </p>
        </div>
        <div>
          <h4 className="text-card text-ink">Checking the signature</h4>
          <p className="mb-2 mt-1 text-support text-ink-2">Check the signature against the raw bytes, compare in constant time, and answer with a 2xx status quickly.</p>
          <CodeBlock code={VERIFY_SNIPPET} label="Python signature check" />
        </div>
      </div>
    </details>
  );
}

const cleanupText = (policy: string | null): string => (policy === "auto" ? "Removal is requested right after a document passes verification." : "An operator approves removal first.");

export function RepairCard({ appMode, group, singleUser }: { appMode: boolean; group?: SettingsGroup; singleUser?: { configured: boolean; cleanupPolicy: string } }) {
  const [open, setOpen] = useState(false);
  const configured = appMode ? !!group?.configured : !!singleUser?.configured;
  const url = field(group, "webhook_url");
  const policy = appMode ? ((field(group, "cleanup_policy")?.value as string | null) ?? null) : (singleUser?.cleanupPolicy ?? null);
  const urlSet = !!url?.has_value;
  const secretSet = !!field(group, "webhook_secret")?.has_value;

  return (
    <Card>
      <CardHeader
        title="Repair webhook"
        description="Lets RAGGuard ask your own ingestion worker to re-index documents. RAGGuard never writes to your systems itself."
        actions={
          <>
            <ConfigBadge configured={configured} />
            {appMode && group ? <Button variant={configured ? "secondary" : "primary"} onClick={() => setOpen(true)}>{group.updated_at ? "Edit" : "Configure"}</Button> : null}
          </>
        }
      />
      <CardBody className="space-y-5">
        {!appMode ? <EnvNote>Set RAGI_REPAIR_WEBHOOK_URL and RAGI_REPAIR_WEBHOOK_SECRET (and RAGI_CLEANUP_POLICY for removal) in the server&apos;s environment.</EnvNote> : null}

        {appMode || singleUser ? (
          <dl className="grid gap-x-6 gap-y-3 sm:grid-cols-3">
            {appMode ? (
              <>
                <div className="min-w-0">
                  <dt className="text-support text-ink-2">Webhook URL</dt>
                  <dd className="mt-0.5 break-all text-body text-ink">{url?.value ? String(url.value) : "Not set"}</dd>
                </div>
                <div>
                  <dt className="text-support text-ink-2">Signing secret</dt>
                  <dd className={`mt-0.5 text-body ${secretSet ? "text-success" : "text-ink"}`}>{secretSet ? "Saved" : "Not set"}</dd>
                </div>
              </>
            ) : null}
            <div>
              <dt className="text-support text-ink-2">Vector removal</dt>
              <dd className="mt-0.5 text-body text-ink">
                <span className="font-medium">{policy === "auto" ? "Automatic" : "Manual"}.</span> {cleanupText(policy)}
              </dd>
            </div>
          </dl>
        ) : null}

        {appMode && urlSet && !secretSet ? (
          <p className="flex items-start gap-2 rounded-control bg-warning-bg px-3 py-2 text-support text-ink" role="note">
            <AlertTriangle className="mt-px h-4 w-4 shrink-0 text-warning" aria-hidden />
            A signing secret is required before anything is sent. Open Edit and add one.
          </p>
        ) : null}

        <div>
          <h3 className="text-card text-ink">How a repair works</h3>
          <ol className="mt-2 list-decimal space-y-1.5 pl-5 text-body text-ink-2 marker:text-ink-3">
            {STEPS.map((s) => (
              <li key={s}>{s}</li>
            ))}
          </ol>
        </div>

        <WebhookDetails />

        {appMode && group ? <SavedStatus group={group} showTest={false} /> : null}
      </CardBody>
      {appMode && group ? (
        <SettingsModal
          group={group}
          open={open}
          onOpenChange={setOpen}
          title="Repair webhook"
          testLabel="Check settings"
          testNote="Checks that the values are valid and that the address is allowed. It does not send anything to your worker."
        />
      ) : null}
    </Card>
  );
}
