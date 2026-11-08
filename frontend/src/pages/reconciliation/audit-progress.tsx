import { useEffect, useRef } from "react";
import { Card } from "@/components/ui/card";
import { cn } from "@/lib/cn";
import { timeAgo } from "@/lib/format";
import type { AuditRun } from "@/types/api";

/** A progress bar with no known end. It slides with the Web Animations API (no stylesheet needed) and holds still for people who ask for less motion. */
export function IndeterminateBar({ label, className }: { label: string; className?: string }) {
  const thumb = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = thumb.current;
    if (!el || typeof el.animate !== "function" || window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const anim = el.animate([{ transform: "translateX(-100%)" }, { transform: "translateX(350%)" }], { duration: 1500, iterations: Infinity, easing: "ease-in-out" });
    return () => anim.cancel();
  }, []);

  return (
    <div className={cn("h-2 w-full overflow-hidden rounded-full bg-surface", className)} role="progressbar" aria-label={label} aria-busy>
      <div ref={thumb} className="h-full w-[30%] rounded-full bg-brand" />
    </div>
  );
}

/** Shown while an audit is running. The page behind it keeps showing the last finished audit. */
export function AuditProgressCard({ run }: { run: AuditRun | null }) {
  const scope = run?.scope.tenant ? ` for tenant ${run.scope.tenant}` : "";
  return (
    <Card className="p-5" role="status">
      <h2 className="text-section text-ink">Audit in progress</h2>
      <p className="mt-0.5 text-support text-ink-2">
        Comparing your source, manifest and index{scope}.{run?.status === "running" ? ` Started ${timeAgo(run.started_at)}.` : ""} This page updates when it finishes.
      </p>
      <IndeterminateBar label="Audit in progress" className="mt-4" />
    </Card>
  );
}
