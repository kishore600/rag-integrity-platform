import { Bell, BookOpen, Database, FileText, GitCompareArrows, History, LayoutDashboard, Lock, Plug, Settings, ShieldAlert, UserCog, type LucideIcon } from "lucide-react";

export interface NavItem {
  to: string;
  label: string;
  icon: LucideIcon;
  /** Shows the open-issue count next to the label. */
  badge?: "issues";
  end?: boolean;
}

export const NAV: NavItem[] = [
  { to: "/", label: "Overview", icon: LayoutDashboard, end: true },
  { to: "/data-sources", label: "Data Sources", icon: Database },
  { to: "/reconciliation", label: "Reconciliation", icon: GitCompareArrows },
  { to: "/issues", label: "Integrity Issues", icon: ShieldAlert, badge: "issues" },
  { to: "/isolation", label: "Isolation", icon: Lock },
  { to: "/documents", label: "Documents", icon: FileText },
  { to: "/audit-history", label: "Audit History", icon: History },
  { to: "/integrations", label: "Integrations", icon: Plug },
  { to: "/alerts", label: "Alerts", icon: Bell },
  { to: "/settings", label: "Settings", icon: Settings },
];

/**
 * The way into the user guide and the video. It sits below the ten pages, set apart, because it is help about the product and not one of
 * its pages (the account menu has the same link). `/help` is public, so the landing page links to it too.
 */
export const HELP_ITEM: NavItem = { to: "/help", label: "Help and user guide", icon: BookOpen };

/** The operator's dashboard of every account and audit. Shown only to emails listed in RAGI_ADMIN_EMAILS. */
export const ADMIN_ITEM: NavItem = { to: "/admin", label: "Admin", icon: UserCog };
