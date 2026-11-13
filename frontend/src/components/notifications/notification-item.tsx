import { CircleAlert, CircleCheck, Info, TriangleAlert, type LucideIcon } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Tip } from "@/components/ui/menus";
import { cn } from "@/lib/cn";
import { timeAgo } from "@/lib/format";
import { useNotificationActions } from "@/hooks/use-notification-actions";
import type { AppNotification } from "@/types/api";

const TONE: Record<AppNotification["tone"], { icon: LucideIcon; text: string; bg: string }> = {
  success: { icon: CircleCheck, text: "text-success", bg: "bg-success-bg" },
  info: { icon: Info, text: "text-info", bg: "bg-info-bg" },
  warning: { icon: TriangleAlert, text: "text-warning", bg: "bg-warning-bg" },
  critical: { icon: CircleAlert, text: "text-critical", bg: "bg-critical-bg" },
};

/**
 * One notification: what happened, and the next step as buttons. The same component is used in the bell and on the Notifications page.
 * `compact` keeps the details out (the bell is small); the page shows everything.
 */
export function NotificationItem({ n, compact, onNavigate }: { n: AppNotification; compact?: boolean; onNavigate?: () => void }) {
  const { perform, blockedReason, busy } = useNotificationActions(onNavigate);
  const tone = TONE[n.tone] ?? TONE.info;
  const Icon = tone.icon;
  const unread = !n.read_at;

  return (
    <li className={cn("flex gap-3 px-3 py-3", unread ? "bg-brand-light/40" : "")} data-notification-id={n.id}>
      <span className={cn("mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full", tone.bg)} aria-hidden>
        <Icon className={cn("h-4 w-4", tone.text)} />
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex items-start gap-2">
          <h3 className="min-w-0 flex-1 break-words text-card text-ink">{n.title}</h3>
          {unread ? <span className="mt-1.5 h-2 w-2 shrink-0 rounded-full bg-brand" aria-label="Unread" /> : null}
        </div>
        <p className="mt-0.5 break-words text-support text-ink-2">{n.body}</p>
        {!compact && n.details.length > 0 ? (
          <ul className="mt-1.5 list-disc space-y-0.5 pl-4 text-support text-ink-2">
            {n.details.map((d, i) => (
              <li key={i} className="break-words">{d}</li>
            ))}
          </ul>
        ) : null}
        <p className="mt-1 text-support text-ink-3">
          {timeAgo(n.created_at)}
          {n.emailed_at ? " · emailed" : ""}
        </p>
        {n.actions.length > 0 ? (
          <div className="mt-2 flex flex-wrap gap-2">
            {n.actions.map((a) => {
              const why = blockedReason(n, a);
              const done = n.done_action === a.id;
              const button = (
                <Button
                  key={a.id}
                  size="sm"
                  variant={a.primary && !done ? "primary" : "secondary"}
                  disabled={!!why}
                  loading={busy(a) && !done}
                  onClick={() => perform(n, a)}
                >
                  {done ? <CircleCheck className="h-3.5 w-3.5 text-success" aria-hidden /> : null}
                  {done ? `${a.label}: done` : a.label}
                </Button>
              );
              return why ? (
                <Tip key={a.id} content={why}>
                  <span tabIndex={0}>{button}</span>
                </Tip>
              ) : (
                button
              );
            })}
          </div>
        ) : null}
      </div>
    </li>
  );
}
