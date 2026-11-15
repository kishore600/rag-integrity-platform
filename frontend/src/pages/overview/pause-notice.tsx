import { CirclePause } from "lucide-react";
import { Button } from "@/components/ui/button";
import { LinkButton } from "@/components/shared/link-button";
import { useRunAudit } from "@/hooks/use-run-audit";
import type { AuditPause } from "@/types/api";
import { Banner } from "./ui";

/**
 * The last whole audit ran out of time reading an index too big for this host. Running it again would fail the same way
 * (and read the whole index for minutes first), so Run audit is switched off and this says what to change instead.
 */
export function PauseNotice({ pause }: { pause: AuditPause }) {
  const { run, running } = useRunAudit();
  return (
    <Banner tone="warning" icon={CirclePause}>
      <p className="font-semibold">Audit paused: your index is too big to read in one go here</p>
      <p className="mt-1">Running it again would fail the same way, so Run audit is switched off until the setup changes. It switches itself back on once you turn on the setting below.</p>
      <ul className="mt-2 space-y-1">
        {pause.steps.map((step) => (
          <li key={step}>{step}</li>
        ))}
      </ul>
      <div className="mt-3 flex flex-wrap items-center gap-3">
        <LinkButton variant="primary" size="sm" to="/settings?tab=policy">
          Open audit policy settings
        </LinkButton>
        <Button
          variant="ghost"
          size="sm"
          loading={running}
          onClick={() => run({ force: true })}
          title="Only if a worker on a server (ragi worker) is running: it has no time limit. On the website alone this fails again."
        >
          Run it anyway
        </Button>
      </div>
    </Banner>
  );
}
