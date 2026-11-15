import { useQueryClient } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import { Activity, History, RefreshCw, ScanSearch, ShieldOff, Users } from "lucide-react";
import { useMemo, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardHeader } from "@/components/ui/card";
import { SearchInput } from "@/components/ui/form";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/menus";
import { DataTable } from "@/components/shared/data-table";
import { KpiCard, PageHeader, ProgressBar } from "@/components/shared/page";
import { EmptyState, ErrorState } from "@/components/shared/states";
import { HealthBadge, RunStatusBadge } from "@/components/shared/status";
import { useAdminAudits, useAdminOverview, useAdminUsers, useSession } from "@/hooks/queries";
import { formatDate, formatDateTime, formatDuration, formatNumber, timeAgo } from "@/lib/format";
import type { AdminAudit, AdminUser } from "@/types/api";

const num = "text-right tabular-nums";

/** Display names of the settings groups a workspace can save (the admin view only knows which ones exist, never their values). */
const SYSTEM_LABEL: Record<string, string> = {
  s3: "S3",
  qdrant: "Qdrant",
  pgvector: "pgvector",
  manifest: "Manifest",
  repair: "Repair worker",
  alerts: "Alerts",
  email: "Email",
};
const CORE_SYSTEMS = new Set(["s3", "qdrant", "pgvector", "manifest"]);

const pct = (part: number, whole: number) => (whole > 0 ? Math.round((part / whole) * 100) : 0);

function WhenCell({ iso }: { iso: string | null }) {
  return (
    <div className="whitespace-nowrap">
      <p className="text-ink">{timeAgo(iso)}</p>
      <p className="text-support text-ink-2">{formatDate(iso)}</p>
    </div>
  );
}

const userColumns: ColumnDef<AdminUser>[] = [
  {
    id: "account",
    header: "Account",
    accessorFn: (u) => u.email,
    cell: ({ row }) => (
      <div className="min-w-0">
        <p className="truncate font-medium text-ink" title={row.original.email}>{row.original.email}</p>
        <p className="truncate text-support text-ink-2">{row.original.workspace}</p>
      </div>
    ),
  },
  { id: "signed_up", header: "Signed up", accessorFn: (u) => u.created_at ?? "", cell: ({ row }) => <WhenCell iso={row.original.created_at} /> },
  { id: "active", header: "Last active", accessorFn: (u) => u.last_active_at ?? "", cell: ({ row }) => <WhenCell iso={row.original.last_active_at} /> },
  {
    id: "connected",
    header: "Connections",
    accessorFn: (u) => (u.connected ? 1 : 0) + u.systems.length / 100,
    cell: ({ row }) => {
      const shown = row.original.systems.filter((s) => CORE_SYSTEMS.has(s));
      return (
        <div className="space-y-1">
          <Badge tone={row.original.connected ? "success" : "neutral"} dot>{row.original.connected ? "Ready to audit" : "Not connected"}</Badge>
          {shown.length ? <p className="text-support text-ink-2">{shown.map((s) => SYSTEM_LABEL[s] ?? s).join(", ")}</p> : null}
        </div>
      );
    },
  },
  {
    id: "audits",
    header: "Audits",
    accessorFn: (u) => u.audits,
    meta: { className: num },
    cell: ({ row }) => (
      <div>
        <p className="text-ink">{formatNumber(row.original.audits)}</p>
        {row.original.audits_failed ? <p className="text-support text-critical">{formatNumber(row.original.audits_failed)} failed</p> : null}
      </div>
    ),
  },
  {
    id: "last_audit",
    header: "Last audit",
    accessorFn: (u) => u.last_audit?.started_at ?? "",
    cell: ({ row }) => {
      const a = row.original.last_audit;
      if (!a) return <span className="text-ink-2">None yet</span>;
      return (
        <div className="space-y-1 whitespace-nowrap">
          <div className="flex items-center gap-2">
            <RunStatusBadge status={a.status} />
            {a.health_score !== null && a.health_score !== undefined ? <HealthBadge score={a.health_score} /> : null}
          </div>
          <p className="text-support text-ink-2">
            {timeAgo(a.started_at)}
            {a.documents !== null && a.documents !== undefined ? ` · ${formatNumber(a.documents)} documents` : ""}
          </p>
        </div>
      );
    },
  },
];

const auditColumns: ColumnDef<AdminAudit>[] = [
  { id: "started", header: "Started", accessorFn: (a) => a.started_at ?? "", cell: ({ row }) => <span className="whitespace-nowrap text-ink">{formatDateTime(row.original.started_at)}</span> },
  {
    id: "account",
    header: "Account",
    accessorFn: (a) => a.email ?? "",
    cell: ({ row }) => (
      <div className="min-w-0">
        <p className="truncate text-ink" title={row.original.email ?? undefined}>{row.original.email ?? "—"}</p>
        <p className="truncate text-support text-ink-2">{row.original.workspace}</p>
      </div>
    ),
  },
  {
    id: "status",
    header: "Status",
    accessorFn: (a) => a.status,
    cell: ({ row }) => (
      <div className="space-y-1">
        <RunStatusBadge status={row.original.status} />
        {row.original.error ? (
          <p className="max-w-[280px] truncate text-support text-critical" title={row.original.error}>{row.original.error}</p>
        ) : null}
      </div>
    ),
  },
  {
    id: "type",
    header: "Type",
    accessorFn: (a) => `${a.kind} ${a.trigger}`,
    cell: ({ row }) => (
      <span className="whitespace-nowrap text-ink-2">
        {row.original.kind} · {row.original.trigger}
      </span>
    ),
  },
  { id: "documents", header: "Documents", accessorFn: (a) => a.documents ?? -1, meta: { className: num }, cell: ({ row }) => formatNumber(row.original.documents) },
  { id: "findings", header: "Findings", accessorFn: (a) => a.findings ?? -1, meta: { className: num }, cell: ({ row }) => formatNumber(row.original.findings) },
  { id: "health", header: "Health", accessorFn: (a) => a.health_score ?? -1, cell: ({ row }) => <HealthBadge score={row.original.health_score} /> },
  {
    id: "duration",
    header: "Duration",
    accessorFn: (a) => a.duration_seconds ?? -1,
    meta: { className: num },
    cell: ({ row }) => <span className="whitespace-nowrap">{formatDuration(row.original.duration_seconds)}</span>,
  },
];

function Funnel({ signedUp, connected, audited }: { signedUp: number; connected: number; audited: number }) {
  const steps = [
    { label: "Signed up", value: signedUp, hint: "Created an account" },
    { label: "Connected", value: connected, hint: "Saved a source and an index" },
    { label: "Ran an audit", value: audited, hint: "At least one audit, any result" },
  ];
  return (
    <Card>
      <CardHeader title="From sign-up to first audit" description="How far each account has got. Percentages are of everyone who signed up." />
      <ol className="grid gap-5 p-5 md:grid-cols-3">
        {steps.map((s, i) => (
          <li key={s.label}>
            <div className="flex items-baseline justify-between gap-2">
              <p className="text-card text-ink">
                <span className="mr-1.5 text-ink-3">{i + 1}.</span>
                {s.label}
              </p>
              <p className="tabular-nums text-ink">
                <span className="text-section">{formatNumber(s.value)}</span>
                <span className="ml-1.5 text-support text-ink-2">{pct(s.value, signedUp)}%</span>
              </p>
            </div>
            <div className="mt-2">
              <ProgressBar value={pct(s.value, signedUp)} tone={i === 2 ? "success" : "brand"} label={`${s.label}: ${pct(s.value, signedUp)}% of sign-ups`} />
            </div>
            <p className="mt-1.5 text-support text-ink-2">{s.hint}</p>
          </li>
        ))}
      </ol>
    </Card>
  );
}

/** `/admin`: every account and every audit on this server. Only for emails listed in RAGI_ADMIN_EMAILS. */
export default function AdminPage() {
  const session = useSession().data;
  const isAdmin = !!session?.user?.admin;
  const qc = useQueryClient();
  const overview = useAdminOverview(isAdmin);
  const users = useAdminUsers(isAdmin);
  const audits = useAdminAudits(isAdmin);
  const [search, setSearch] = useState("");

  const filteredUsers = useMemo(() => {
    const q = search.trim().toLowerCase();
    const rows = users.data ?? [];
    return q ? rows.filter((u) => u.email.includes(q) || u.workspace.toLowerCase().includes(q)) : rows;
  }, [users.data, search]);
  const filteredAudits = useMemo(() => {
    const q = search.trim().toLowerCase();
    const rows = audits.data ?? [];
    return q ? rows.filter((a) => (a.email ?? "").includes(q) || a.workspace.toLowerCase().includes(q)) : rows;
  }, [audits.data, search]);

  if (session && !isAdmin) {
    return (
      <Card>
        <EmptyState icon={ShieldOff} title="This page isn't available" description="The admin dashboard is only open to the operator of this server." />
      </Card>
    );
  }

  const o = overview.data;
  const loading = overview.isLoading || !session;
  const refreshing = overview.isFetching || users.isFetching || audits.isFetching;

  return (
    <>
      <PageHeader
        title="Admin"
        description="Everyone who signed up, when they were last active, and every audit on this server. Read-only: no passwords, keys or connection details are shown."
        actions={
          <Button onClick={() => void qc.invalidateQueries({ queryKey: ["admin"] })} loading={refreshing}>
            <RefreshCw className="h-4 w-4" aria-hidden /> Refresh
          </Button>
        }
      />

      {overview.isError ? (
        <Card className="mb-6">
          <ErrorState error={overview.error} onRetry={() => void overview.refetch()} />
        </Card>
      ) : (
        <div className="space-y-6">
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            <KpiCard label="Accounts" icon={Users} loading={loading} value={formatNumber(o?.users.total)} hint={`${formatNumber(o?.users.new_7d)} new in 7 days · ${formatNumber(o?.users.new_30d)} in 30`} />
            <KpiCard label="Active in the last 7 days" icon={Activity} tone="success" loading={loading} value={formatNumber(o?.users.active_7d)} hint="Signed in or used the app" />
            <KpiCard
              label="Audits in the last 7 days"
              icon={History}
              tone={o?.audits.failed_7d ? "warning" : "brand"}
              loading={loading}
              value={formatNumber(o?.audits.last_7d)}
              hint={o?.audits.failed_7d ? `${formatNumber(o.audits.failed_7d)} failed` : "None failed"}
            />
            <KpiCard
              label="Audits, all time"
              icon={ScanSearch}
              tone="info"
              loading={loading}
              value={formatNumber(o?.audits.total)}
              hint={o?.audits.running ? `${formatNumber(o.audits.running)} running or waiting now` : "None running now"}
            />
          </div>

          {o ? <Funnel signedUp={o.funnel.signed_up} connected={o.funnel.connected} audited={o.funnel.audited} /> : null}
        </div>
      )}

      <Tabs defaultValue="accounts" className="mt-6">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <TabsList aria-label="Admin sections">
            <TabsTrigger value="accounts">Accounts{users.data ? ` (${formatNumber(users.data.length)})` : ""}</TabsTrigger>
            <TabsTrigger value="audits">Audits{audits.data ? ` (${formatNumber(audits.data.length)})` : ""}</TabsTrigger>
          </TabsList>
          <SearchInput value={search} onChange={setSearch} placeholder="Filter by email or workspace" className="w-full sm:w-72" aria-label="Filter by email or workspace" />
        </div>
        <TabsContent value="accounts">
          <Card>
            {users.isError ? (
              <ErrorState error={users.error} onRetry={() => void users.refetch()} />
            ) : (
              <DataTable
                label="Accounts"
                data={filteredUsers}
                columns={userColumns}
                loading={users.isLoading || !session}
                getRowId={(u) => u.email}
                initialSort={[{ id: "signed_up", desc: true }]}
                empty={<EmptyState icon={Users} title={search ? "No account matches" : "No accounts yet"} compact />}
              />
            )}
          </Card>
        </TabsContent>
        <TabsContent value="audits">
          <Card>
            {audits.isError ? (
              <ErrorState error={audits.error} onRetry={() => void audits.refetch()} />
            ) : (
              <DataTable
                label="Audits"
                data={filteredAudits}
                columns={auditColumns}
                loading={audits.isLoading || !session}
                getRowId={(a) => a.id}
                initialSort={[{ id: "started", desc: true }]}
                empty={<EmptyState icon={History} title={search ? "No audit matches" : "No audits yet"} compact />}
                note={audits.data && audits.data.length >= 200 ? "Showing the latest 200 audits." : undefined}
              />
            )}
          </Card>
        </TabsContent>
      </Tabs>
    </>
  );
}
