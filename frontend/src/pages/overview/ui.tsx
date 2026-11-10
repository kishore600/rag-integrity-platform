import { ArrowRight, Info, Play, TriangleAlert, type LucideIcon } from "lucide-react";
import type { ReactNode } from "react";
import { Button } from "@/components/ui/button";
import { Tip } from "@/components/ui/menus";
import { LinkButton } from "@/components/shared/link-button";
import { useRunAudit } from "@/hooks/use-run-audit";
import { cn } from "@/lib/cn";
import { documentName } from "@/lib/format";

const BANNER = {
  success: { box: "border-success/25 bg-success-bg", icon: "text-success" },
  info: { box: "border-info/25 bg-info-bg", icon: "text-info" },
  warning: { box: "border-warning/30 bg-warning-bg", icon: "text-warning" },
  critical: { box: "border-critical/25 bg-critical-bg", icon: "text-critical" },
} as const;

/** A full-width notice. `critical` is announced to screen readers immediately; the others politely. */
export function Banner({ tone = "info", icon, children, className }: { tone?: keyof typeof BANNER; icon?: LucideIcon; children: ReactNode; className?: string }) {
  const Icon = icon ?? (tone === "info" ? Info : TriangleAlert);
  return (
    <div role={tone === "critical" ? "alert" : "status"} className={cn("flex items-start gap-2.5 rounded-card border px-4 py-3", BANNER[tone].box, className)}>
      <Icon className={cn("mt-0.5 h-4 w-4 shrink-0", BANNER[tone].icon)} aria-hidden />
      <div className="min-w-0 text-body text-ink">{children}</div>
    </div>
  );
}

/** The one "Run audit" button for this page. Disabled with the reason as a tooltip until the workspace can run one. */
export function RunAuditButton({ label = "Run audit", variant = "primary" }: { label?: string; variant?: "primary" | "secondary" }) {
  const { run, running, disabledReason } = useRunAudit();
  const button = (
    <Button variant={variant} onClick={() => run()} loading={running} disabled={!!disabledReason && !running}>
      {!running ? <Play className="h-4 w-4" aria-hidden /> : null}
      {running ? "Audit running" : label}
    </Button>
  );
  if (disabledReason && !running) {
    return (
      <Tip content={disabledReason}>
        <span tabIndex={0} className="inline-flex rounded-control">
          {button}
        </span>
      </Tip>
    );
  }
  return button;
}

/** A link at the bottom of a card. */
export function CardFooterLink({ to, children }: { to: string; children: ReactNode }) {
  return (
    <div className="border-t border-line px-5 py-3">
      <LinkButton variant="link" to={to}>
        {children}
        <ArrowRight className="h-3.5 w-3.5" aria-hidden />
      </LinkButton>
    </div>
  );
}

/** A table that only assistive technology sees: the text alternative to a chart. */
export function SrTable({ caption, columns, rows }: { caption: string; columns: string[]; rows: (string | number)[][] }) {
  return (
    <table className="sr-only">
      <caption>{caption}</caption>
      <thead>
        <tr>
          {columns.map((c) => (
            <th key={c} scope="col">
              {c}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.map((r, i) => (
          <tr key={i}>
            {r.map((cell, j) =>
              j === 0 ? (
                <th key={j} scope="row">
                  {cell}
                </th>
              ) : (
                <td key={j}>{cell}</td>
              ),
            )}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export const capitalize = (s: string): string => s.charAt(0).toUpperCase() + s.slice(1).replace(/[_-]/g, " ");

/** How a document id reads in a list: its file name, or a plain label for tenant-wide issues. */
export const documentLabel = (documentId: string): string => (documentId === "*" ? "Whole tenant" : documentName(documentId));
