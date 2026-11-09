import { Bell, CircleCheck, CircleX, Loader2, ShieldCheck, TriangleAlert } from "lucide-react";
import type { ReactNode } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Modal } from "@/components/ui/overlays";
import { Skeleton } from "@/components/shared/states";
import { SeverityBadge } from "@/components/shared/status";
import type { useIsolationDrill } from "@/hooks/queries";
import { ApiError, errorMessage } from "@/lib/api";
import { cn } from "@/lib/cn";
import { documentName, formatNumber } from "@/lib/format";
import { issueLabel } from "@/lib/issue-meta";
import type { DrillResult } from "@/types/api";
import { plural } from "./meta";

type Drill = ReturnType<typeof useIsolationDrill>;

/**
 * The alert text is Slack-style markup (*bold*, `code`). It is turned into React elements, never into HTML, so nothing in it
 * can run. Line breaks and bullets are kept by `whitespace-pre-wrap` on the box that holds it.
 */
function AlertText({ text }: { text: string }) {
  const parts = text.split(/(\*[^*\n]+\*|`[^`\n]+`)/g);
  return (
    <>
      {parts.map((p, i) => {
        if (p.length > 2 && p.startsWith("*") && p.endsWith("*")) return <strong key={i} className="font-semibold">{p.slice(1, -1)}</strong>;
        if (p.length > 2 && p.startsWith("`") && p.endsWith("`")) return <code key={i} className="rounded bg-workspace px-1 py-0.5 font-mono text-support">{p.slice(1, -1)}</code>;
        return <span key={i}>{p}</span>;
      })}
    </>
  );
}

function Heading({ children }: { children: ReactNode }) {
  return <h3 className="mb-2 text-card text-ink">{children}</h3>;
}

/** The promise, always visible: whatever state the drill is in, nothing is being changed. */
function SafeNote() {
  return (
    <div className="flex items-start gap-2.5 rounded-control border border-info/25 bg-info-bg px-3 py-2.5">
      <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0 text-info" aria-hidden />
      <p className="text-body text-ink">
        <span className="font-semibold">Nothing is changed.</span> This is a practice run. It only reads from your systems: it writes nothing, saves no issue and sends no alert.
      </p>
    </div>
  );
}

function Running() {
  return (
    <div role="status" aria-live="polite" aria-busy className="space-y-3">
      <div className="flex items-center gap-2 text-body text-ink">
        <Loader2 className="h-4 w-4 animate-spin text-brand" aria-hidden />
        Running the drill on one of your documents…
      </div>
      <p className="text-support text-ink-2">This can take a few seconds.</p>
      <div className="space-y-2" aria-hidden>
        <Skeleton className="h-16 w-full" />
        <Skeleton className="h-10 w-full" />
        <Skeleton className="h-24 w-full" />
      </div>
    </div>
  );
}

function Failed({ error }: { error: unknown }) {
  const upstream = error instanceof ApiError && (error.status === 502 || error.status === 503 || error.status === 504);
  return (
    <div role="alert" className="flex items-start gap-2.5 rounded-card border border-critical/25 bg-critical-bg px-4 py-3">
      <TriangleAlert className="mt-0.5 h-4 w-4 shrink-0 text-critical" aria-hidden />
      <div className="min-w-0">
        <p className="text-card text-ink">The drill could not run</p>
        <p className="mt-0.5 break-words text-body text-ink">{errorMessage(error)}</p>
        {upstream ? <p className="mt-1 text-support text-ink">One of your systems did not answer in time. Nothing was changed. Try again in a moment.</p> : null}
      </div>
    </div>
  );
}

function Result({ r }: { r: DrillResult }) {
  const doc = r.document;
  const name = documentName(doc.document_id);
  return (
    <div className="space-y-5">
      <div>
        <Heading>Document used</Heading>
        <dl className="grid gap-x-6 gap-y-3 rounded-card border border-line bg-app p-4 sm:grid-cols-3">
          <div className="min-w-0">
            <dt className="text-support text-ink-2">Tenant</dt>
            <dd className="mt-0.5 break-words text-body font-medium text-ink">{doc.tenant_id}</dd>
          </div>
          <div className="min-w-0">
            <dt className="text-support text-ink-2">Document</dt>
            <dd className="mt-0.5 break-all text-body font-medium text-ink" title={doc.document_id}>
              {name}
              {name !== doc.document_id ? <span className="block text-support font-normal text-ink-2">{doc.document_id}</span> : null}
            </dd>
          </div>
          <div className="min-w-0">
            <dt className="text-support text-ink-2">Vectors</dt>
            <dd className="mt-0.5 text-body font-medium tabular-nums text-ink">{formatNumber(doc.points)}</dd>
          </div>
        </dl>
      </div>

      <div>
        <Heading>What the drill pretended</Heading>
        <p className="text-body text-ink">{r.simulated}</p>
      </div>

      <div>
        <div
          role="status"
          className={cn("flex items-start gap-2.5 rounded-card border px-4 py-3", r.caught ? "border-success/25 bg-success-bg" : "border-critical/25 bg-critical-bg")}
        >
          {r.caught ? <CircleCheck className="mt-0.5 h-5 w-5 shrink-0 text-success" aria-hidden /> : <CircleX className="mt-0.5 h-5 w-5 shrink-0 text-critical" aria-hidden />}
          <div className="min-w-0">
            <p className="text-card text-ink">{r.caught ? "The audit caught it" : "The audit did not catch it"}</p>
            <p className="mt-0.5 text-body text-ink">
              {r.caught ? "A real leak like this would be raised as a critical Tenant mismatch finding." : "The audit did not raise a Tenant mismatch finding for this pretend leak."}
            </p>
          </div>
        </div>
      </div>

      <div>
        <Heading>
          What the audit would raise{" "}
          <span className="font-normal text-ink-2">
            ({formatNumber(r.findings.length)} {plural(r.findings.length, "finding")})
          </span>
        </Heading>
        {r.findings.length === 0 ? (
          <p className="text-body text-ink-2">No finding would be raised.</p>
        ) : (
          <ul className="space-y-2">
            {r.findings.map((f, i) => (
              <li key={`${f.type}-${f.tenant_id}-${f.document_id}-${i}`} className="rounded-control border border-line p-3">
                <div className="flex flex-wrap items-center gap-2">
                  <SeverityBadge severity={f.severity} />
                  <span className="min-w-0 break-words text-body font-medium text-ink">{f.title}</span>
                </div>
                <p className="mt-1 break-words text-support text-ink-2">
                  {issueLabel(f.type)} · tenant {f.tenant_id} · {f.document_id === "*" ? "whole tenant" : documentName(f.document_id)}
                </p>
                <p className="mt-1.5 break-words text-body text-ink">{f.detail}</p>
              </li>
            ))}
          </ul>
        )}
      </div>

      <div>
        <Heading>Alert it would have sent</Heading>
        {r.would_alert ? (
          <div className="flex items-start gap-2.5 rounded-control bg-surface px-3 py-2.5">
            <Bell className="mt-0.5 h-4 w-4 shrink-0 text-ink-2" aria-hidden />
            <div className="min-w-0 flex-1">
              <SeverityBadge severity={r.would_alert.severity} />
              <p className="mt-1.5 whitespace-pre-wrap break-words rounded-control border border-line bg-workspace px-3 py-2 text-body text-ink">
                <AlertText text={r.would_alert.text} />
              </p>
              <p className="mt-2 text-support text-ink-2">{r.would_alert.note}</p>
            </div>
          </div>
        ) : (
          <p className="text-body text-ink-2">No alert would be sent.</p>
        )}
      </div>

      <div className="flex items-start gap-2.5 rounded-control border border-success/25 bg-success-bg px-3 py-2.5">
        <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0 text-success" aria-hidden />
        <p className="text-body text-ink">{r.nothing_changed}</p>
      </div>
    </div>
  );
}

/**
 * The isolation drill: a read-only practice run on one of the user's own documents. The page starts it (so the same button can be
 * offered in several places); this dialog shows it running, what it found, or why it could not run.
 */
export function DrillDialog({ open, onOpenChange, drill, onRun }: { open: boolean; onOpenChange: (open: boolean) => void; drill: Drill; onRun: () => void }) {
  return (
    <Modal
      open={open}
      onOpenChange={onOpenChange}
      size="lg"
      title={
        <span className="flex flex-wrap items-center gap-2">
          Isolation drill
          <Badge tone="info" className="tracking-wide">
            DRILL
          </Badge>
        </span>
      }
      description="Shows what RAGGuard does when one of your documents is indexed under the wrong tenant."
      footer={
        <>
          <Button variant="secondary" onClick={() => onOpenChange(false)}>
            Close
          </Button>
          <Button variant="primary" onClick={onRun} loading={drill.isPending}>
            Run it again
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <SafeNote />
        {drill.isPending ? <Running /> : drill.isError ? <Failed error={drill.error} /> : drill.data ? <Result r={drill.data} /> : null}
      </div>
    </Modal>
  );
}
