import { toast } from "sonner";
import { useNavigate } from "react-router-dom";
import { errorMessage } from "@/lib/api";
import type { AppNotification, AuditRequest, NotificationAction } from "@/types/api";
import { useDeletionCheck, useMarkNotification, useNotificationDone, useOverview } from "./queries";
import { useRunAudit } from "./use-run-audit";

/** A page of this app: a path that starts with one slash. Anything else in a stored notification is ignored, never followed. */
const isAppPath = (target: string): boolean => target.startsWith("/") && !target.startsWith("//") && !target.includes("\\");

/**
 * Makes the buttons of a notification work. A `link` opens a page of the app. A `post` does what it says through the same
 * endpoint and the same signed-in session as the page's own buttons (only the two known endpoints are ever called), and the notification
 * then remembers that it was done. Used by the bell and by the Notifications page, so a button behaves the same in both.
 */
export function useNotificationActions(afterNavigate?: () => void) {
  const navigate = useNavigate();
  const { run, running } = useRunAudit();
  const check = useDeletionCheck();
  const read = useMarkNotification();
  const done = useNotificationDone();
  const resumable = useOverview(true).data?.resumable_audit ?? null;

  /** Why a button cannot be pressed right now, or null. */
  function blockedReason(n: AppNotification, a: NotificationAction): string | null {
    if (a.kind !== "post") return null;
    if (n.done_action === a.id) return "Already done from this notification";
    if (a.target === "/api/audits") {
      if (running) return "An audit is already running";
      if (a.body && (a.body as AuditRequest).resume && resumable?.run_id !== n.run_id) return "This audit has already been resumed or replaced by a newer one";
    }
    if (a.target === "/api/deletion-check" && check.isPending) return "The check is running";
    return null;
  }

  function perform(n: AppNotification, a: NotificationAction) {
    if (blockedReason(n, a)) return;
    const finish = () => done.mutate({ id: n.id, action: a.id });
    if (a.kind === "link") {
      if (!isAppPath(a.target)) return;
      if (!n.read_at) read.mutate(n.id);
      afterNavigate?.();
      navigate(a.target);
      return;
    }
    if (a.target === "/api/audits") {
      run((a.body ?? {}) as AuditRequest, { onStarted: finish });
      return;
    }
    if (a.target === "/api/deletion-check") {
      const id = toast.loading("Checking the deleted documents…", { description: "Looking in the source, the manifest and the index" });
      check.mutate(undefined, {
        onSuccess: (r) => {
          const s = r.summary;
          if (s.documents_checked === 0) toast.info("Nothing to verify", { id, description: r.note });
          else if (s.vectors_remaining > 0)
            toast.warning(`Checked ${s.documents_checked} deleted document${s.documents_checked === 1 ? "" : "s"}`, {
              id,
              description: `${s.vectors_remaining} vector${s.vectors_remaining === 1 ? " is" : "s are"} still in the index${s.retrievable ? `, and ${s.retrievable} can still be found by a search` : ""}. Open Integrity Issues for the clean-up.`,
            });
          else toast.success(`Checked ${s.documents_checked} deleted document${s.documents_checked === 1 ? "" : "s"}`, { id, description: "Every vector is gone and none can be found by a search." });
          finish();
        },
        onError: (err) => toast.error("Couldn't run the deletion check", { id, description: errorMessage(err) }),
      });
    }
  }

  return { perform, blockedReason, busy: (a: NotificationAction) => a.kind === "post" && (a.target === "/api/audits" ? running : check.isPending) };
}
