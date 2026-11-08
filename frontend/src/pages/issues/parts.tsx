/** Small presentational pieces shared by the issues, plans and impact views. */
import { useState, type ReactNode } from "react";
import { Field, Textarea } from "@/components/ui/form";
import { ConfirmDialog } from "@/components/ui/overlays";
import { cn } from "@/lib/cn";

/** A compact label and number, used for summaries inside cards and drawers. */
export function Stat({ label, value, hint, className }: { label: string; value: ReactNode; hint?: ReactNode; className?: string }) {
  return (
    <div className={cn("min-w-0", className)}>
      <p className="text-support text-ink-2">{label}</p>
      <p className="mt-0.5 truncate text-section tabular-nums text-ink">{value}</p>
      {hint ? <p className="mt-0.5 text-support text-ink-2">{hint}</p> : null}
    </div>
  );
}

/** Confirm ignoring one or many issues, with an optional reason that is stored in the issue history. */
export function IgnoreDialog({ open, onOpenChange, count, onConfirm }: { open: boolean; onOpenChange: (open: boolean) => void; count: number; onConfirm: (reason: string) => Promise<unknown> }) {
  const [reason, setReason] = useState("");
  return (
    <ConfirmDialog
      open={open}
      onOpenChange={(o) => {
        if (!o) setReason("");
        onOpenChange(o);
      }}
      title={count === 1 ? "Ignore this issue?" : `Ignore ${count} issues?`}
      description="Ignored issues stay on record but no longer count as open, and they are left out of repair plans. You can reopen them at any time."
      confirmLabel={count === 1 ? "Ignore issue" : `Ignore ${count} issues`}
      onConfirm={() => onConfirm(reason.trim())}
    >
      <Field label="Reason (optional)" help="Saved in the issue history so your team knows why. Up to 500 characters.">
        {(p) => <Textarea {...p} value={reason} onChange={(e) => setReason(e.target.value)} maxLength={500} placeholder="For example: expected, this document is being retired" />}
      </Field>
    </ConfirmDialog>
  );
}

/** A tinted callout used for guidance and warnings inside cards. */
export function Callout({ tone = "neutral", children, role }: { tone?: "neutral" | "success" | "warning" | "critical" | "info"; children: ReactNode; role?: "alert" | "status" }) {
  const style = {
    neutral: "bg-surface text-ink-2",
    success: "bg-success-bg text-success",
    warning: "bg-warning-bg text-ink",
    critical: "bg-critical-bg text-critical",
    info: "bg-info-bg text-ink",
  }[tone];
  return (
    <div className={cn("rounded-control px-3 py-2.5 text-body", style)} role={role}>
      {children}
    </div>
  );
}
