import { toast } from "sonner";
import { errorMessage } from "@/lib/api";
import type { AuditRequest } from "@/types/api";
import { useOverview, useSession, useStartAudit } from "./queries";

/**
 * Starts an audit and narrates it. One hook for every "Run audit" button, so they behave identically:
 * disabled until the source and the vector index are connected, disabled while a run is in progress, and toasts for start / finish / failure.
 */
export function useRunAudit() {
  const session = useSession().data;
  const overview = useOverview(true);
  const start = useStartAudit();
  const connected = session ? (session.app ? !!session.ready : true) : false;
  const running = start.isPending || !!overview.data?.audit_running;

  /** `onStarted` runs once the server has accepted the request (a notification uses it to remember that its button was pressed). */
  function run(req: AuditRequest = {}, opts: { onStarted?: () => void } = {}) {
    if (running) return;
    const id = toast.loading("Running audit…", { description: "Comparing your source with your vector index" });
    start.mutate(req, {
      onSuccess: (r) => {
        opts.onStarted?.();
        if (r.status === "completed") {
          const n = r.stats?.findings_total;
          toast.success("Audit complete", { id, description: n === undefined ? undefined : n === 0 ? "No integrity issues found." : `${n} integrity issue${n === 1 ? "" : "s"} found.` });
        } else if (r.status === "partial") {
          const scan = r.stats?.scan;
          toast.warning("Audit stopped part-way", { id, description: scan?.documents_total ? `Checked ${scan.documents_done} of ${scan.documents_total} documents; the rest is not reported. Resume it from Audit History.` : "Open Audit History for the details." });
        } else if (r.status === "failed") {
          toast.error("Audit failed", { id, description: "Open Audit History for the reason." });
        } else {
          toast.success("Audit started", { id, description: "It continues in the background; this page updates as it finishes." });
        }
      },
      onError: (err) => toast.error("Couldn't start the audit", { id, description: errorMessage(err) }),
    });
  }

  const disabledReason = !connected ? "Connect your data sources first" : running ? "An audit is already running" : null;
  return { run, running, connected, disabledReason };
}
