import { Play } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Tip } from "@/components/ui/menus";
import { useRunAudit } from "@/hooks/use-run-audit";

/** Starts a full audit: the isolation picture is built from one. Disabled, with the reason in a tooltip, until the workspace can run it. */
export function RunFullAuditButton({ variant = "primary", size }: { variant?: "primary" | "secondary"; size?: "sm" | "md" }) {
  const { run, running, disabledReason } = useRunAudit();
  const blocked = !!disabledReason && !running;
  const button = (
    <Button variant={variant} size={size} onClick={() => run({})} loading={running} disabled={blocked}>
      {running ? null : <Play className="h-4 w-4" aria-hidden />}
      {running ? "Audit running" : "Run full audit"}
    </Button>
  );
  if (!blocked) return button;
  return (
    <Tip content={disabledReason}>
      <span tabIndex={0} className="inline-flex rounded-control">
        {button}
      </span>
    </Tip>
  );
}
