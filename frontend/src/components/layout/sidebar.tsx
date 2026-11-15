import { NavLink } from "react-router-dom";
import { Logo } from "@/components/brand/logo";
import { cn } from "@/lib/cn";
import { formatNumber } from "@/lib/format";
import { useOverview, useSession } from "@/hooks/queries";
import { ADMIN_ITEM, HELP_ITEM, NAV, type NavItem } from "./nav";

function MenuLink({ item, open, onNavigate }: { item: NavItem; open?: number; onNavigate?: () => void }) {
  return (
    <NavLink
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
  );
}

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

      <nav aria-label="Main" className="flex-1 overflow-y-auto px-3 py-4">
        <div className="space-y-0.5">
          {NAV.map((item) => (
            <MenuLink key={item.to} item={item} open={open} onNavigate={onNavigate} />
          ))}
        </div>
        {/* help about the product, set apart from its pages */}
        <div className="mt-3 space-y-0.5 border-t border-white/5 pt-3">
          <MenuLink item={HELP_ITEM} onNavigate={onNavigate} />
          {/* the operator's dashboard, only for emails in RAGI_ADMIN_EMAILS (the server refuses everyone else too) */}
          {session?.user?.admin ? <MenuLink item={ADMIN_ITEM} onNavigate={onNavigate} /> : null}
        </div>
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
