import { Mail } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Field, Input, Switch, Textarea } from "@/components/ui/form";
import { Modal } from "@/components/ui/overlays";
import { useEmailPlan } from "@/hooks/queries";
import { errorMessage } from "@/lib/api";
import { Callout } from "./parts";

/** Email a repair plan to the people who will fix it. Nothing is sent until a person types the recipients and presses Send. */
export function EmailPlanDialog({ planId, open, onOpenChange, configured }: { planId: string; open: boolean; onOpenChange: (open: boolean) => void; configured: boolean }) {
  const email = useEmailPlan();
  const [to, setTo] = useState("");
  const [note, setNote] = useState("");
  const [attach, setAttach] = useState(true);
  const [error, setError] = useState<string | null>(null);

  async function send() {
    setError(null);
    try {
      const plan = await email.mutateAsync({ id: planId, to, note: note.trim() || undefined, attach_payload: attach });
      const sent = [...(plan.events ?? [])].reverse().find((e) => e.event === "emailed");
      const count = typeof sent?.details?.count === "number" ? sent.details.count : undefined;
      toast.success("Email sent", { description: count ? `${count} ${count === 1 ? "person" : "people"} will find the plan in their inbox.` : "The plan is in their inbox." });
      setTo("");
      setNote("");
      onOpenChange(false);
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  return (
    <Modal
      open={open}
      onOpenChange={(o) => {
        if (!email.isPending) {
          setError(null);
          onOpenChange(o);
        }
      }}
      title="Email this plan"
      description="Send the plan to the people who will fix it, so they do not need to open RAGGuard."
      size="md"
      footer={
        configured ? (
          <>
            <Button variant="secondary" onClick={() => onOpenChange(false)} disabled={email.isPending}>Cancel</Button>
            <Button variant="primary" onClick={send} loading={email.isPending} disabled={!to.trim()}>
              <Mail className="h-4 w-4" aria-hidden /> Send email
            </Button>
          </>
        ) : (
          <Button variant="secondary" onClick={() => onOpenChange(false)}>Close</Button>
        )
      }
    >
      {configured ? (
        <div className="space-y-4">
          <Field label="Send to" required help="Up to 10 addresses, separated by commas or spaces.">
            {(f) => <Input {...f} type="text" value={to} onChange={(e) => setTo(e.target.value)} placeholder="dev@your-company.com, lead@your-company.com" autoComplete="off" />}
          </Field>
          <Field label="Note (optional)" help="Shown at the top of the email.">
            {(f) => <Textarea {...f} value={note} onChange={(e) => setNote(e.target.value)} maxLength={1000} placeholder="For example: please fix by Friday" />}
          </Field>
          <div className="flex items-start justify-between gap-4">
            <div>
              <p className="text-card text-ink">Attach the exact payload (JSON)</p>
              <p className="mt-0.5 text-support text-ink-2">What your repair worker would receive. Useful when a developer fixes the documents by hand or builds a worker.</p>
            </div>
            <Switch checked={attach} onChange={setAttach} label="Attach the exact payload (JSON)" />
          </div>
          <Callout tone="neutral">
            The email has a readable summary with a table of the documents and what to do, a CSV with every document (it opens in Excel and Google Sheets),
            and a link back to this plan.
          </Callout>
          {error ? <p className="rounded-control bg-critical-bg px-3 py-2 text-support text-critical" role="alert">{error}</p> : null}
        </div>
      ) : (
        <Callout tone="warning" role="status">
          Email is not set up yet. Add your mail server under <Link to="/integrations" className="font-medium text-brand hover:underline">Integrations</Link> (or set
          RAGI_SMTP_HOST and RAGI_SMTP_FROM on a self-hosted server), then come back. You can still download the plan as a CSV.
        </Callout>
      )}
    </Modal>
  );
}
