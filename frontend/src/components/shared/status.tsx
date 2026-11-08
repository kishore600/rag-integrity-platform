import { Badge, type Tone } from "@/components/ui/badge";
import { DOC_STATE_LABEL, documentState, type DocState } from "@/lib/issue-meta";
import type { AuditRun, DocumentRow, IssueStatus, RepairPlan, Severity } from "@/types/api";

const SEVERITY_TONE: Record<Severity, Tone> = { critical: "critical", high: "warning", medium: "info", low: "neutral", info: "neutral" };
const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1).replace(/_/g, " ");

export const severityTone = (s: Severity): Tone => SEVERITY_TONE[s];

export function SeverityBadge({ severity }: { severity: Severity | null | undefined }) {
  if (!severity) return <span className="text-ink-3">—</span>;
  return <Badge tone={SEVERITY_TONE[severity]} dot>{cap(severity)}</Badge>;
}

const ISSUE_STATUS_TONE: Record<IssueStatus, Tone> = { open: "warning", resolved: "success", ignored: "neutral" };
export const IssueStatusBadge = ({ status }: { status: IssueStatus }) => <Badge tone={ISSUE_STATUS_TONE[status]} dot>{cap(status)}</Badge>;

const DOC_TONE: Record<DocState, Tone> = { healthy: "success", stale: "warning", missing: "critical", processing: "info", failed: "critical" };
export const DocStateBadge = ({ doc }: { doc: Pick<DocumentRow, "status" | "issue_types"> }) => {
  const s = documentState(doc);
  return <Badge tone={DOC_TONE[s]} dot>{DOC_STATE_LABEL[s]}</Badge>;
};

const RUN_TONE: Record<AuditRun["status"], Tone> = { running: "info", completed: "success", failed: "critical" };
export const RunStatusBadge = ({ status }: { status: AuditRun["status"] }) => <Badge tone={RUN_TONE[status]} dot>{cap(status)}</Badge>;

const PLAN_TONE: Record<RepairPlan["status"], Tone> = {
  draft: "neutral",
  triggered: "info",
  partial: "warning",
  failed: "critical",
  cleanup_pending: "warning",
  cleanup_triggered: "info",
  completed: "success",
};
export const PlanStatusBadge = ({ status }: { status: RepairPlan["status"] }) => <Badge tone={PLAN_TONE[status]} dot>{cap(status)}</Badge>;

/** Health score as a coloured pill: 90+ healthy, 70+ needs attention, below is unhealthy. */
export const healthTone = (score: number | null | undefined): Tone => (score === null || score === undefined ? "neutral" : score >= 90 ? "success" : score >= 70 ? "warning" : "critical");
export const HealthBadge = ({ score }: { score: number | null | undefined }) => <Badge tone={healthTone(score)}>{score === null || score === undefined ? "—" : `${score.toFixed(1)}%`}</Badge>;
