import type { Tone } from "@/components/ui/badge";
import type { IsolationCheckStatus, IsolationOverallStatus, IsolationTenantStatus } from "@/types/api";

/** Per tenant. `rank` is the sort order (worst first), the same order the server uses. */
export const TENANT_STATUS: Record<IsolationTenantStatus, { label: string; tone: Tone; rank: number }> = {
  leak: { label: "Leak", tone: "critical", rank: 0 },
  attention: { label: "Needs attention", tone: "warning", rank: 1 },
  clean: { label: "Clean", tone: "success", rank: 2 },
  single_tenant: { label: "Single tenant", tone: "neutral", rank: 3 },
};

const CHECK_STATUS: Record<IsolationCheckStatus, { label: string; tone: Tone }> = {
  pass: { label: "Passed", tone: "success" },
  warn: { label: "Warning", tone: "warning" },
  fail: { label: "Failed", tone: "critical" },
  na: { label: "Not applicable", tone: "neutral" },
};

/** When the whole check was limited, a check that could not run was "not checked", not "not applicable". */
export function checkStatus(status: IsolationCheckStatus, overall: IsolationOverallStatus): { label: string; tone: Tone } {
  if (status === "na" && overall === "limited") return { label: "Not checked", tone: "neutral" };
  return CHECK_STATUS[status];
}

/** "1 document" / "2 documents". */
export const plural = (n: number, one: string, many = `${one}s`): string => (n === 1 ? one : many);

/** The exact label of the audit policy setting that turns the limit on (src/ragintegrity/workspaces.py). */
export const SOURCE_ONLY_LABEL = "Only audit documents found in the source (S3)";
