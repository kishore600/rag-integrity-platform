import { CircleMinus, Info, ShieldCheck, ShieldX, TriangleAlert, type LucideIcon } from "lucide-react";
import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { Mono } from "@/components/shared/page";
import { cn } from "@/lib/cn";
import { formatDateTime, timeAgo } from "@/lib/format";
import { links } from "@/lib/links";
import type { IsolationAvailable, IsolationOverallStatus } from "@/types/api";

const STYLE: Record<IsolationOverallStatus, { box: string; icon: string; Icon: LucideIcon; title: string }> = {
  leak: { box: "border-critical/25 bg-critical-bg", icon: "text-critical", Icon: ShieldX, title: "Leak found" },
  attention: { box: "border-warning/30 bg-warning-bg", icon: "text-warning", Icon: TriangleAlert, title: "Needs attention" },
  clean: { box: "border-success/25 bg-success-bg", icon: "text-success", Icon: ShieldCheck, title: "No leaks found" },
  limited: { box: "border-info/25 bg-info-bg", icon: "text-info", Icon: Info, title: "This check is limited" },
  not_applicable: { box: "border-line bg-surface", icon: "text-ink-2", Icon: CircleMinus, title: "Only one tenant" },
};

/** The server writes its sentences for Markdown too (the evidence report), so a `code` span is shown as code, without the backticks. */
function withCode(text: string): ReactNode[] {
  return text.split(/`([^`]+)`/g).map((part, i) => (i % 2 === 1 ? <Mono key={i}>{part}</Mono> : part));
}

/** The result in one glance: the server's own sentence, coloured by how serious it is, and which audit it is based on. */
export function StatusBanner({ data }: { data: IsolationAvailable }) {
  const { overall, audit } = data;
  const s = STYLE[overall.status];
  const when = audit.finished_at;
  return (
    <div role="status" className={cn("flex items-start gap-3 rounded-card border px-4 py-3.5", s.box)}>
      <s.Icon className={cn("mt-0.5 h-5 w-5 shrink-0", s.icon)} aria-hidden />
      <div className="min-w-0 flex-1">
        <p className="text-card text-ink">{s.title}</p>
        <p className="mt-0.5 text-body text-ink">{withCode(overall.summary)}</p>
        <p className="mt-1.5 text-support text-ink">
          Based on the full audit that finished{" "}
          <span title={formatDateTime(when)} className="font-medium">
            {timeAgo(when)}
          </span>
          .{" "}
          <Link to={links.audit(audit.run_id)} className="font-medium text-brand hover:underline">
            View audit
          </Link>
        </p>
      </div>
    </div>
  );
}
