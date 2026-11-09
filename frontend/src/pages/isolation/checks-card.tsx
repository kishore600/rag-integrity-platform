import { CircleCheck, CircleMinus, CircleX, TriangleAlert, type LucideIcon } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Card, CardHeader } from "@/components/ui/card";
import { Skeleton } from "@/components/shared/states";
import { cn } from "@/lib/cn";
import type { IsolationCheck, IsolationCheckStatus, IsolationOverallStatus } from "@/types/api";
import { checkStatus } from "./meta";

const ICON: Record<IsolationCheckStatus, { Icon: LucideIcon; box: string }> = {
  pass: { Icon: CircleCheck, box: "bg-success-bg text-success" },
  warn: { Icon: TriangleAlert, box: "bg-warning-bg text-warning" },
  fail: { Icon: CircleX, box: "bg-critical-bg text-critical" },
  na: { Icon: CircleMinus, box: "bg-surface text-ink-3" },
};

const TITLE = "Checks";
const DESCRIPTION = "The five checks behind the result above. Each one reads what the last full audit already read.";

export function ChecksCard({ checks, overall }: { checks: IsolationCheck[]; overall: IsolationOverallStatus }) {
  return (
    <Card>
      <CardHeader title={TITLE} description={DESCRIPTION} />
      <ul className="divide-y divide-line">
        {checks.map((c) => {
          const { Icon, box } = ICON[c.status];
          const label = checkStatus(c.status, overall);
          return (
            <li key={c.name} className="flex items-start gap-3 px-5 py-3.5">
              <span className={cn("mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full", box)}>
                <Icon className="h-4 w-4" aria-hidden />
              </span>
              <div className="min-w-0 flex-1">
                <p className="text-body font-medium text-ink">{c.name}</p>
                <p className="mt-0.5 text-support text-ink-2">{c.detail}</p>
              </div>
              <Badge tone={label.tone} className="mt-0.5">
                {label.label}
              </Badge>
            </li>
          );
        })}
      </ul>
    </Card>
  );
}

export function ChecksSkeleton() {
  return (
    <Card>
      <CardHeader title={TITLE} description={DESCRIPTION} />
      <ul className="divide-y divide-line">
        {[0, 1, 2, 3, 4].map((i) => (
          <li key={i} className="flex items-start gap-3 px-5 py-3.5">
            <Skeleton className="h-7 w-7 rounded-full" />
            <div className="flex-1 space-y-1.5">
              <Skeleton className="h-4 w-1/2" />
              <Skeleton className="h-3 w-3/4" />
            </div>
            <Skeleton className="h-5 w-16 rounded-full" />
          </li>
        ))}
      </ul>
    </Card>
  );
}
