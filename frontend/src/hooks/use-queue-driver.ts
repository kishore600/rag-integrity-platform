import { useQueryClient, type QueryClient } from "@tanstack/react-query";
import { useEffect } from "react";
import { toast } from "sonner";
import { errorMessage, post } from "@/lib/api";
import type { WorkerStepResult } from "@/types/api";
import { invalidateData, qk, useOverview, useSession } from "./queries";

/**
 * Makes sure a queued audit never waits for nobody.
 *
 * With `RAGI_AUDIT_QUEUE` on, "Run audit" only puts the audit in a queue and a worker (`ragi worker`) carries it out. If no worker
 * has picked it up for a while the server says so (`waiting_for_worker`), and this page does the worker's job itself: it calls
 * `POST /api/worker/step` (one stretch of work, the same call a scheduled job would make) and, when a stretch stops part-way and
 * queues the next one, calls it again, until the audit is over. A real worker is never in the way: whoever claims the audit first
 * gets it, and the other call finds nothing to do.
 *
 * It only works while the page is open. That is why a worker on a server is still the right set-up for a very large index.
 */

const RETRY_AFTER_ERROR_MS = 30_000;
const MAX_ERRORS_IN_A_ROW = 3;
const MAX_STRETCHES = 500; // a safety stop: a 4-million-vector index is a few dozen stretches

// Module state, not component state: the work carries on when the user moves to another page of the dashboard.
let driving = false;
let errorsInARow = 0;
let retryAt = 0;

async function drive(qc: QueryClient): Promise<void> {
  driving = true;
  toast.info("Running your audit from this page", {
    id: "queue-driver",
    description: "No worker picked it up, so this page is doing it. Keep this tab open until it finishes.",
  });
  try {
    for (let stretch = 0; stretch < MAX_STRETCHES; stretch++) {
      const out = await post<WorkerStepResult>("/api/worker/step");
      errorsInARow = 0;
      void qc.invalidateQueries({ queryKey: qk.overview }); // the banner follows the audit while it works
      if (out.status === "idle") break; // a worker (or another tab) got there first
      if (!(out.status === "partial" && out.next)) break; // finished, failed, or stalled: the overview tells the person
    }
  } catch (err) {
    errorsInARow += 1;
    retryAt = Date.now() + RETRY_AFTER_ERROR_MS;
    if (errorsInARow >= MAX_ERRORS_IN_A_ROW) {
      toast.error("This page could not run the waiting audit", { id: "queue-driver", description: `${errorMessage(err)} Start a worker (ragi worker) or try again later.` });
    }
  } finally {
    driving = false;
    void invalidateData(qc);
  }
}

export function useQueueDriver(): void {
  const qc = useQueryClient();
  const session = useSession().data;
  const overview = useOverview(session ? (session.app ? !!session.ready : true) : false).data;
  const waiting = overview?.audit_progress?.state === "waiting_for_worker";

  useEffect(() => {
    if (!waiting) return;
    const attempt = () => {
      if (driving || Date.now() < retryAt || errorsInARow >= MAX_ERRORS_IN_A_ROW) return;
      void drive(qc);
    };
    attempt();
    const timer = setInterval(attempt, 5_000); // a stretch that failed is tried again after a pause, not in a tight loop
    return () => clearInterval(timer);
  }, [waiting, qc]);
}
