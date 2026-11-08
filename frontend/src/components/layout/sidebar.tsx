import { NavLink } from "react-router-dom";
import { Logo } from "@/components/brand/logo";
import { cn } from "@/lib/cn";
import { formatNumber } from "@/lib/format";
import { useOverview, useSession } from "@/hooks/queries";
import { NAV } from "./nav";

export function SidebarContent({ onNavigate }: { onNavigate?: () => void }) {
  const session = useSession().data;
  const overview = useOverview(session ? (session.app ? !!session.ready : true) : false);
  const open = overview.data?.issues.open;
  const environment = session?.demo ? "Demo" : "Live";

  return (
    <div className="flex h-full flex-col bg-sidebar text-sidebar-text">
      <div className="flex h-topbar shrink-0 items-center border-b border-white/5 px-5">
        <Logo size={34} />
      </div>

      <nav aria-label="Main" className="flex-1 space-y-0.5 overflow-y-auto px-3 py-4">
        {NAV.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.end}
            onClick={onNavigate}
            className={({ isActive }) =>
              cn(
                "group flex h-10 items-center gap-3 rounded-control px-3 text-body font-medium transition-colors",
                isActive ? "bg-sidebar-active text-white" : "hover:bg-sidebar-hover hover:text-white",
              )
            }
          >
            {({ isActive }) => (
              <>
                <item.icon className={cn("h-[18px] w-[18px] shrink-0", isActive ? "text-sidebar-icon" : "text-sidebar-text group-hover:text-sidebar-icon")} aria-hidden />
                <span className="flex-1 truncate">{item.label}</span>
                {item.badge === "issues" && open ? (
                  <span className="rounded-full bg-white/10 px-2 py-0.5 text-support font-medium tabular-nums text-white" aria-label={`${open} open issues`}>
                    {formatNumber(open)}
                  </span>
                ) : null}
              </>
            )}
          </NavLink>
        ))}
      </nav>

      <div className="shrink-0 border-t border-white/5 p-4">
        <div className="rounded-control bg-sidebar-hover px-3 py-2.5">
          <div className="flex items-center gap-2">
            <span className={cn("h-2 w-2 rounded-full", session?.demo ? "bg-warning" : "bg-success")} aria-hidden />
            <span className="text-support font-semibold uppercase tracking-wide text-white">{environment}</span>
          </div>
          <p className="mt-1 truncate text-support">{session?.workspace?.name ?? (session?.demo ? "Synthetic demo data" : "Single-user server")}</p>
          <p className="text-support text-sidebar-text/70">v{session?.version ?? "—"}</p>
        </div>
      </div>
    </div>
  );
}

export function Sidebar() {
  return (
    <aside className="hidden h-full w-sidebar shrink-0 lg:block" aria-label="Sidebar">
      <SidebarContent />
    </aside>
  );
}
