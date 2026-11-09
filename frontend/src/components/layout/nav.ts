import { Bell, Database, FileText, GitCompareArrows, History, LayoutDashboard, Lock, Plug, Settings, ShieldAlert, type LucideIcon } from "lucide-react";

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
