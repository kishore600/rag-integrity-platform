import { useQueryClient } from "@tanstack/react-query";
import { Bell, BookOpen, ChevronDown, LogOut, Menu, Play, Settings as SettingsIcon } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { NotificationItem } from "@/components/notifications/notification-item";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel, DropdownMenuSeparator, DropdownMenuTrigger, Tip } from "@/components/ui/menus";
import { errorMessage, post } from "@/lib/api";
import { formatNumber, initials, timeAgo } from "@/lib/format";
import { links } from "@/lib/links";
import { qk, useMarkAllNotificationsRead, useNotifications, useOverview, useSession } from "@/hooks/queries";
import { useRunAudit } from "@/hooks/use-run-audit";
import { GlobalSearch } from "./global-search";

function NotificationsMenu() {
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  const session = useSession().data;
  const overview = useOverview(session ? (session.app ? !!session.ready : true) : false).data;
  const list = useNotifications(10);
  const readAll = useMarkAllNotificationsRead();
  const items = list.data?.items ?? [];
  const unread = list.data?.unread ?? 0;
  const sev = overview?.issues.by_severity;
  const openIssues = overview?.issues.open ?? 0;
  const last = overview?.latest_run;

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (box.current && !box.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  function go(path: string) {
    setOpen(false);
    navigate(path);
  }

  return (
    <div ref={box} className="relative">
      <Button
        variant="ghost"
        size="icon"
        className="relative"
        aria-label={`Notifications${unread ? `, ${unread} unread` : ""}`}
        aria-expanded={open}
        aria-haspopup="dialog"
        aria-controls="notifications-panel"
        onClick={() => setOpen((o) => !o)}
      >
        <Bell className="h-[18px] w-[18px]" />
        {unread > 0 ? (
          <span className="absolute -right-0.5 -top-0.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-critical px-1 text-[10px] font-semibold leading-none text-white ring-2 ring-white" aria-hidden>
            {unread > 9 ? "9+" : unread}
          </span>
        ) : null}
      </Button>
      {open ? (
        <div
          id="notifications-panel"
          role="dialog"
          aria-label="Notifications"
          className="anim-pop fixed inset-x-3 top-16 z-50 overflow-hidden rounded-card border border-line bg-workspace shadow-pop sm:absolute sm:inset-x-auto sm:right-0 sm:top-full sm:mt-1.5 sm:w-[420px]"
        >
          <div className="flex items-center justify-between gap-2 border-b border-line px-3 py-2.5">
            <h2 className="text-card text-ink">Notifications{unread ? <span className="ml-2 text-support font-normal text-ink-2">{unread} unread</span> : null}</h2>
            <Button variant="ghost" size="sm" disabled={unread === 0} loading={readAll.isPending} onClick={() => readAll.mutate()}>
              Mark all read
            </Button>
          </div>
          <div className="border-b border-line px-3 py-2 text-support text-ink-2">
            {overview ? (
              <>
                {openIssues === 0 ? "No open integrity issues." : `${formatNumber(openIssues)} open issue${openIssues === 1 ? "" : "s"}`}
                {openIssues > 0 && (sev?.critical || sev?.high) ? ` (${sev?.critical ?? 0} critical, ${sev?.high ?? 0} high)` : ""}
                {" · "}
                {last ? `last audit ${timeAgo(last.finished_at ?? last.started_at)} (${last.status})` : "no audit has run yet"}
              </>
            ) : (
              "Connect your data sources to see alerts."
            )}
          </div>
          <div className="max-h-[min(60vh,520px)] overflow-y-auto">
            {list.isError ? (
              <p className="px-3 py-4 text-support text-ink-2">Notifications could not be loaded. They will be tried again shortly.</p>
            ) : items.length === 0 ? (
              <p className="px-3 py-4 text-support text-ink-2">{list.isPending ? "Loading…" : "Nothing yet. After an audit finishes, what it found and the next step appear here."}</p>
            ) : (
              <ul className="divide-y divide-line" aria-label="Latest notifications">
                {items.map((n) => (
                  <NotificationItem key={n.id} n={n} compact onNavigate={() => setOpen(false)} />
                ))}
              </ul>
            )}
          </div>
          <div className="flex flex-wrap items-center gap-x-4 gap-y-1 border-t border-line px-3 py-2.5 text-support">
            <button type="button" className="text-brand hover:underline" onClick={() => go(links.notifications())}>See all notifications</button>
            <button type="button" className="text-brand hover:underline" onClick={() => go(links.issues())}>Integrity issues</button>
            <button type="button" className="text-brand hover:underline" onClick={() => go("/alerts")}>Alert settings</button>
          </div>
        </div>
      ) : null}
    </div>
  );
}

function UserMenu() {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const session = useSession().data;
  const email = session?.user?.email;

  async function signOut() {
    try {
      await post("/api/auth/logout");
    } catch (err) {
      toast.error("Couldn't sign out", { description: errorMessage(err) });
      return;
    }
    qc.removeQueries({ predicate: (q) => q.queryKey[0] !== "session" });
    await qc.invalidateQueries({ queryKey: qk.session });
    navigate("/");
  }

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button type="button" className="flex h-10 items-center gap-2 rounded-control pl-1 pr-2 hover:bg-surface" aria-label="Account menu">
          <span className="flex h-8 w-8 items-center justify-center rounded-full bg-brand-light text-support font-semibold text-brand">{email ? initials(email) : "RG"}</span>
          <span className="hidden max-w-[160px] truncate text-body font-medium text-ink md:block">{email ?? "Operator"}</span>
          <ChevronDown className="hidden h-4 w-4 text-ink-2 md:block" aria-hidden />
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent className="w-64">
        <div className="px-2.5 py-2">
          <p className="truncate text-body font-medium text-ink">{email ?? "Operator"}</p>
          <p className="truncate text-support text-ink-2">{session?.workspace?.name ?? (session?.demo ? "Demo workspace" : "Single-user server")}</p>
        </div>
        <DropdownMenuSeparator />
        <DropdownMenuItem onSelect={() => navigate("/settings")}>
          <SettingsIcon className="h-4 w-4 text-ink-2" /> Settings
        </DropdownMenuItem>
        <DropdownMenuItem onSelect={() => navigate("/help")}>
          <BookOpen className="h-4 w-4 text-ink-2" /> Help and user guide
        </DropdownMenuItem>
        {session?.app ? (
          <DropdownMenuItem destructive onSelect={() => void signOut()}>
            <LogOut className="h-4 w-4" /> Sign out
          </DropdownMenuItem>
        ) : null}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

export function Topbar({ onMenu }: { onMenu: () => void }) {
  const { run, running, disabledReason } = useRunAudit();
  const button = (
    <Button variant="primary" onClick={() => run()} loading={running} disabled={!!disabledReason && !running}>
      {!running ? <Play className="h-4 w-4" /> : null}
      <span className="hidden sm:inline">{running ? "Audit running" : "Run audit"}</span>
      <span className="sm:hidden">{running ? "Running" : "Audit"}</span>
    </Button>
  );
  return (
    <header className="flex h-topbar shrink-0 items-center gap-3 border-b border-line bg-workspace px-4 sm:px-6">
      <Button variant="ghost" size="icon" className="lg:hidden" onClick={onMenu} aria-label="Open navigation">
        <Menu className="h-5 w-5" />
      </Button>
      <GlobalSearch />
      <div className="ml-auto flex items-center gap-1.5 sm:gap-2">
        {disabledReason && !running ? (
          <Tip content={disabledReason}>
            <span tabIndex={0}>{button}</span>
          </Tip>
        ) : (
          button
        )}
        <NotificationsMenu />
        <UserMenu />
      </div>
    </header>
  );
}
