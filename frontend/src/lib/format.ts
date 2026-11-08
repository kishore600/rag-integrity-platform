const nf = new Intl.NumberFormat("en-US");
const nf1 = new Intl.NumberFormat("en-US", { maximumFractionDigits: 1 });

export const formatNumber = (n: number | null | undefined): string => (n === null || n === undefined ? "—" : nf.format(n));
export const formatCompact = (n: number | null | undefined): string =>
  n === null || n === undefined ? "—" : new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 1 }).format(n);
export const formatPercent = (n: number | null | undefined, digits = 1): string =>
  n === null || n === undefined ? "—" : `${n.toFixed(digits)}%`;
export const formatUsd = (n: number | null | undefined): string => {
  if (n === null || n === undefined) return "—";
  return `$${n < 1 ? n.toFixed(4) : nf1.format(n)}`;
};

export function formatBytes(bytes: number | null | undefined): string {
  if (!bytes) return "—";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let v = bytes;
  let i = 0;
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024;
    i++;
  }
  return `${i === 0 ? v : v.toFixed(1)} ${units[i]}`;
}

export function formatDuration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) return "—";
  if (seconds < 1) return `${Math.round(seconds * 1000)} ms`;
  if (seconds < 60) return `${seconds.toFixed(1)} s`;
  const m = Math.floor(seconds / 60);
  return `${m}m ${Math.round(seconds - m * 60)}s`;
}

export function timeAgo(iso: string | null | undefined, now: number = Date.now()): string {
  if (!iso) return "—";
  const s = Math.max(0, (now - new Date(iso).getTime()) / 1000);
  if (s < 45) return "just now";
  if (s < 3600) return `${Math.max(1, Math.round(s / 60))} min ago`;
  if (s < 86400) return `${Math.round(s / 3600)} h ago`;
  if (s < 86400 * 30) return `${Math.round(s / 86400)} d ago`;
  return formatDate(iso);
}

export const formatDate = (iso: string | null | undefined): string =>
  iso ? new Date(iso).toLocaleDateString("en-US", { year: "numeric", month: "short", day: "numeric" }) : "—";

export const formatDateTime = (iso: string | null | undefined): string =>
  iso ? new Date(iso).toLocaleString("en-US", { year: "numeric", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }) : "—";

/** First 10 characters of a hash or version id, for compact display. */
export const shortHash = (v: string | null | undefined, n = 10): string => (v ? (v.length > n + 2 ? `${v.slice(0, n)}…` : v) : "—");

/** The file name of a document id such as "policies/leave-policy.md". */
export const documentName = (documentId: string): string => documentId.split("/").filter(Boolean).pop() ?? documentId;

export const initials = (email: string | undefined): string => {
  const base = (email ?? "?").split("@")[0].replace(/[^a-zA-Z0-9]+/g, " ").trim();
  const parts = base.split(" ").filter(Boolean);
  return ((parts[0]?.[0] ?? "?") + (parts[1]?.[0] ?? parts[0]?.[1] ?? "")).toUpperCase();
};
