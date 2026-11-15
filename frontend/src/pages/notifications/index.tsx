import { BellOff, CheckCheck } from "lucide-react";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { NotificationItem } from "@/components/notifications/notification-item";
import { PageHeader } from "@/components/shared/page";
import { EmptyState, QueryState, Skeleton } from "@/components/shared/states";
import { LinkButton } from "@/components/shared/link-button";
import { useMarkAllNotificationsRead, useNotifications } from "@/hooks/queries";

/** Everything an audit has told this workspace, newest first. Each entry has its next step as buttons. Emails link here. */
export default function NotificationsPage() {
  const q = useNotifications(100);
  const readAll = useMarkAllNotificationsRead();
  const unread = q.data?.unread ?? 0;

  return (
    <>
      <PageHeader
        title="Notifications"
        description="What each audit found, and the next step. The same message is emailed after an audit when email is on."
        actions={
          <div className="flex items-center gap-2">
            <LinkButton variant="secondary" to="/alerts">Alert settings</LinkButton>
            <Button variant="secondary" disabled={unread === 0} loading={readAll.isPending} onClick={() => readAll.mutate()}>
              <CheckCheck className="h-4 w-4" aria-hidden /> Mark all read
            </Button>
          </div>
        }
      />
      <QueryState query={q} skeleton={<Skeleton className="h-64" />}>
        {(data) =>
          data.items.length === 0 ? (
            <Card>
              <EmptyState icon={BellOff} title="No notifications yet" description="After an audit finishes, what it found and what to do about it appears here." />
            </Card>
          ) : (
            <Card>
              <ul className="divide-y divide-line" aria-label="Notifications">
                {data.items.map((n) => (
                  <NotificationItem key={n.id} n={n} />
                ))}
              </ul>
            </Card>
          )
        }
      </QueryState>
    </>
  );
}
