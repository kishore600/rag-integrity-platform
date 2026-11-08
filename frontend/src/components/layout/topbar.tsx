import { useQueryClient } from "@tanstack/react-query";
import { Bell, ChevronDown, LogOut, Menu, Play, Settings as SettingsIcon } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel, DropdownMenuSeparator, DropdownMenuTrigger, Tip } from "@/components/ui/menus";
import { errorMessage, post } from "@/lib/api";
import { formatNumber, initials, timeAgo } from "@/lib/format";
import { links } from "@/lib/links";
import { qk, useOverview, useSession } from "@/hooks/queries";
import { useRunAudit } from "@/hooks/use-run-audit";
import { GlobalSearch } from "./global-search";

function NotificationsMenu() {
  const navigate = useNavigate();
  const session = useSession().data;
  const overview = useOverview(session ? (session.app ? !!session.ready : true) : false).data;
  const sev = overview?.issues.by_severity;
  const open = overview?.issues.open ?? 0;
  const urgent = (sev?.critical ?? 0) + (sev?.high ?? 0);
  const last = overview?.latest_run;

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" size="icon" className="relative" aria-label={`Notifications${urgent ? `, ${urgent} critical or high issues` : ""}`}>
          <Bell className="h-[18px] w-[18px]" />
          {urgent > 0 ? <span className="absolute right-1.5 top-1.5 h-2 w-2 rounded-full bg-critical ring-2 ring-white" aria-hidden /> : null}
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent className="w-80">
        <DropdownMenuLabel className="font-medium text-ink">Needs attention</DropdownMenuLabel>
        {overview ? (
          <>
            <div className="px-2.5 pb-2 text-body text-ink">
              {open === 0 ? "No open integrity issues." : <><span className="font-semibold tabular-nums">{formatNumber(open)}</span> open issue{open === 1 ? "" : "s"}</>}
            </div>
            {open > 0 ? (
              <div className="flex flex-wrap gap-1.5 px-2.5 pb-2">
                {(["critical", "high", "medium", "low"] as const).map((s) =>
                  sev?.[s] ? (
                    <Badge key={s} tone={s === "critical" ? "critical" : s === "high" ? "warning" : s === "medium" ? "info" : "neutral"}>
                      {sev[s]} {s}
                    </Badge>
                  ) : null,
                )}
              </div>
            ) : null}
            <div className="px-2.5 pb-1 text-support text-ink-2">{last ? `Last audit ${timeAgo(last.finished_at ?? last.started_at)} (${last.status})` : "No audit has run yet."}</div>
          </>
        ) : (
          <div className="px-2.5 pb-2 text-support text-ink-2">Connect your data sources to see alerts.</div>
        )}
        <DropdownMenuSeparator />
        <DropdownMenuItem onSelect={() => navigate(links.issues())}>View integrity issues</DropdownMenuItem>
        <DropdownMenuItem onSelect={() => navigate("/alerts")}>Alert settings</DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
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
