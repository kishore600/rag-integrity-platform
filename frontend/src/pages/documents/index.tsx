import type { ColumnDef } from "@tanstack/react-table";
import { AlertTriangle, CheckCircle2, Clock, Database, FileText, Files, FileX, PlayCircle, SearchX } from "lucide-react";
import { useMemo } from "react";
import { useLocation } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { SearchInput } from "@/components/ui/form";
import { Tip } from "@/components/ui/menus";
import { DataTable } from "@/components/shared/data-table";
import { FilterBar, FilterSelect } from "@/components/shared/filters";
import { LinkButton } from "@/components/shared/link-button";
import { KpiCard, PageHeader } from "@/components/shared/page";
import { EmptyState, ErrorState, Skeleton } from "@/components/shared/states";
import { DocStateBadge, SeverityBadge } from "@/components/shared/status";
import { useOverview, useSession } from "@/hooks/queries";
import { useRunAudit } from "@/hooks/use-run-audit";
import { cn } from "@/lib/cn";
import { documentName, formatBytes, formatDateTime, formatNumber, shortHash, timeAgo } from "@/lib/format";
import { documentState, DOC_STATE_LABEL } from "@/lib/issue-meta";
import { links } from "@/lib/links";
import type { DocumentRow } from "@/types/api";
import { oneOf, useDebouncedParam, useParamState } from "@/pages/issues/url-state";
import { DocumentDrawer } from "./document-drawer";
import { DOC_LIMIT, useDocumentList, type DocStatusFilter } from "./use-document-list";

const STATUSES: readonly DocStatusFilter[] = ["all", "healthy", "attention", "degraded", "broken", "pending", "orphaned"];
const STATUS_OPTIONS = [
  { value: "all", label: "All statuses" },
  { value: "healthy", label: "Healthy" },
  { value: "attention", label: "Needs attention" },
  { value: "degraded", label: "Degraded" },
  { value: "broken", label: "Broken" },
  { value: "pending", label: "Pending" },
  { value: "orphaned", label: "Orphaned" },
];

const docKey = (tenant: string, doc: string) => `${tenant}/${doc}`;

/** The `tenant` and `doc` parameters that open a document, taken from links.document so the format lives in one place. */
function drawerParams(tenant: string, doc: string): { tenant: string | null; doc: string | null } {
  const sp = new URLSearchParams(links.document(tenant, doc).split("?")[1] ?? "");
  return { tenant: sp.get("tenant"), doc: sp.get("doc") };
}

function VersionCell({ value, flag }: { value: string | null; flag?: boolean }) {
  if (!value) return <span className="text-ink-3">—</span>;
  return (
    <span className="inline-flex items-center gap-1.5">
      <span className="font-mono text-support text-ink" title={value}>{shortHash(value, 7)}</span>
      {flag ? (
        <Tip content="Index was built from a different version">
          <span className="inline-flex" tabIndex={0} aria-label="Index was built from a different version">
            <AlertTriangle className="h-3.5 w-3.5 text-warning" aria-hidden />
          </span>
        </Tip>
      ) : null}
    </span>
  );
}

const columns: ColumnDef<DocumentRow, any>[] = [ // eslint-disable-line @typescript-eslint/no-explicit-any
  {
    id: "document",
    header: "Document",
    accessorFn: (r) => documentName(r.document_id),
    meta: { className: "min-w-[190px]" },
    cell: ({ row }) => {
      const r = row.original;
      const name = documentName(r.document_id);
      return (
        <div className="min-w-0 max-w-[320px]">
          <p className="truncate font-medium text-ink" title={r.document_id}>{name}</p>
          {name !== r.document_id ? <p className="truncate text-support text-ink-3" title={r.document_id}>{r.document_id}</p> : null}
        </div>
      );
    },
  },
  {
    id: "tenant",
    header: "Tenant",
    accessorFn: (r) => r.tenant_id,
    meta: { className: "min-w-[80px]" },
    cell: ({ row }) => <span className="block max-w-[160px] truncate text-ink-2" title={row.original.tenant_id}>{row.original.tenant_id}</span>,
  },
  {
    id: "state",
    header: "Embedding status",
    accessorFn: (r) => DOC_STATE_LABEL[documentState(r)],
    meta: { className: "w-[150px]" },
    cell: ({ row }) => <DocStateBadge doc={row.original} />,
  },
  {
    id: "source_version",
    header: "Source",
    accessorFn: (r) => r.source_version ?? "",
    meta: { className: "w-[100px]" },
    cell: ({ row }) => <VersionCell value={row.original.source_version} />,
  },
  {
    id: "indexed_version",
    header: "Indexed",
    accessorFn: (r) => r.indexed_version ?? "",
    meta: { className: "w-[110px]" },
    cell: ({ row }) => {
      const r = row.original;
      return <VersionCell value={r.indexed_version} flag={!!r.source_version && !!r.indexed_version && r.source_version !== r.indexed_version} />;
    },
  },
  {
    id: "chunks",
    header: "Chunks",
    accessorFn: (r) => r.indexed_chunks,
    meta: { className: "w-[90px] text-right tabular-nums whitespace-nowrap" },
    cell: ({ row }) => {
      const r = row.original;
      const differs = r.expected_chunks !== null && r.indexed_chunks !== r.expected_chunks;
      return (
        <span className={cn(differs ? "font-medium text-warning" : "text-ink")} title={differs ? "Indexed chunks differ from the chunks expected" : undefined}>
          {formatNumber(r.indexed_chunks)} / {r.expected_chunks === null ? "—" : formatNumber(r.expected_chunks)}
        </span>
      );
    },
  },
  {
    id: "size",
    header: "Size",
    accessorFn: (r) => r.size_bytes,
    meta: { className: "w-[80px] text-right tabular-nums whitespace-nowrap" },
    cell: ({ row }) => <span className="text-ink-2">{formatBytes(row.original.size_bytes)}</span>,
  },
  {
    id: "issues",
    header: "Issues",
    accessorFn: (r) => r.issue_count,
    meta: { className: "w-[130px]" },
    cell: ({ row }) => {
      const r = row.original;
      if (r.issue_count === 0) return <span className="text-ink-3">None</span>;
      return (
        <span className="inline-flex items-center gap-2">
          <span className="min-w-[1.25rem] font-medium tabular-nums text-ink">{formatNumber(r.issue_count)}</span>
          <SeverityBadge severity={r.worst_severity} />
        </span>
      );
    },
  },
  {
    id: "verified",
    header: "Verified",
    accessorFn: (r) => r.last_verified_at,
    meta: { className: "w-[100px] whitespace-nowrap" },
    cell: ({ row }) => <span className="text-ink-2" title={formatDateTime(row.original.last_verified_at)}>{timeAgo(row.original.last_verified_at)}</span>,
  },
];

function KpiStrip({ active, onPick }: { active: DocStatusFilter; onPick: (s: DocStatusFilter) => void }) {
  const session = useSession().data;
  const overview = useOverview(session ? (session.app ? !!session.ready : true) : false);
  if (overview.isPending) {
    return (
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-5" aria-busy aria-label="Loading document counts">
        {[0, 1, 2, 3, 4].map((i) => (
          <Skeleton key={i} className="h-[140px]" />
        ))}
      </div>
    );
  }
  if (overview.isError) return <ErrorState error={overview.error} onRetry={() => void overview.refetch()} compact />;
  const by = overview.data.documents.by_status;
  const get = (k: string) => by[k] ?? 0;
  const items: { key: DocStatusFilter; label: string; value: number; icon: typeof Files; tone: "brand" | "success" | "warning" | "neutral" | "info"; hint?: string }[] = [
    { key: "all", label: "Total", value: overview.data.documents.total, icon: Files, tone: "brand", hint: "Across all tenants" },
    { key: "healthy", label: "Healthy", value: get("healthy"), icon: CheckCircle2, tone: "success", hint: "Index matches the source" },
    { key: "attention", label: "Needs attention", value: get("degraded") + get("broken"), icon: AlertTriangle, tone: "warning", hint: `${formatNumber(get("degraded"))} degraded, ${formatNumber(get("broken"))} broken` },
    { key: "orphaned", label: "Orphaned", value: get("orphaned"), icon: FileX, tone: "neutral", hint: "Gone from the source" },
    { key: "pending", label: "Pending", value: get("pending"), icon: Clock, tone: "info", hint: "Still being processed" },
  ];
  return (
    <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-5" role="group" aria-label="Filter documents by status">
      {items.map((i) => (
        <div key={i.key} className={cn("rounded-card [&>*]:h-full", active === i.key && "ring-2 ring-brand/40")}>
          <KpiCard label={i.label} value={formatNumber(i.value)} icon={i.icon} tone={i.tone} hint={i.hint} onClick={() => onPick(i.key)} />
        </div>
      ))}
    </div>
  );
}

export default function DocumentsPage() {
  const session = useSession().data;
  const connected = session ? (session.app ? !!session.ready : true) : false;
  const location = useLocation();
  const { params, set } = useParamState();
  const overview = useOverview(connected);
  const audit = useRunAudit();
  const search = useDebouncedParam("q");

  const status = oneOf(params.get("status"), STATUSES, "all");
  const tenantParam = params.get("tenant") ?? "";
  const docParam = params.get("doc") ?? "";
  // Opening a row sets `tenant` for the drawer. If the user had no tenant filter, that tenant is not a filter and must not narrow the list.
  const injected = !!docParam && !!(location.state as { injectedTenant?: boolean } | null)?.injectedTenant;
  const tenantFilter = injected ? "" : tenantParam;
  const q = search.value;

  const list = useDocumentList({ status, tenant: tenantFilter, q }, connected);
  const hasFilters = !!(q || tenantFilter || status !== "all");
  const noAuditYet = !!overview.data && overview.data.latest_run === null;

  const tenantOptions = useMemo(() => {
    const ids = new Set((overview.data?.documents.tenants ?? []).map((t) => t.tenant_id));
    if (tenantFilter) ids.add(tenantFilter);
    return [{ value: "", label: "All tenants" }, ...[...ids].sort().map((id) => ({ value: id, label: id }))];
  }, [overview.data, tenantFilter]);

  const clearFilters = () => {
    search.setInput("");
    set({ q: null, status: null, tenant: null, doc: null });
  };

  const openDoc = (r: DocumentRow) => {
    const p = drawerParams(r.tenant_id, r.document_id);
    set({ tenant: p.tenant, doc: p.doc }, { replace: false, state: { injectedTenant: !tenantParam } });
  };
  const closeDoc = () => set({ doc: null, tenant: injected ? null : undefined }, { replace: false });

  const empty = hasFilters ? (
    <EmptyState
      icon={SearchX}
      title="No documents match these filters"
      description="Try a different search, or remove a filter to see more."
      action={<Button variant="secondary" onClick={clearFilters}>Clear filters</Button>}
    />
  ) : noAuditYet ? (
    <EmptyState
      icon={PlayCircle}
      title="No audit has run yet"
      description="Run your first audit and RAGGuard will list every document it compares, with the state of its index."
      action={
        <Button variant="primary" onClick={() => audit.run()} loading={audit.running} disabled={!!audit.disabledReason && !audit.running} title={audit.disabledReason ?? undefined}>
          Run audit
        </Button>
      }
    />
  ) : (
    <EmptyState icon={FileText} title="No documents found" description="The last audit found no documents in your source, manifest or index." />
  );

  return (
    <>
      <PageHeader title="Documents" description="Every document RAGGuard has compared, and what state its index is in." />

      {!connected ? (
        <Card>
          <EmptyState
            icon={Database}
            title="Connect your data sources first"
            description="RAGGuard needs your S3 source, manifest database and Qdrant index before it can compare your documents."
            action={<LinkButton variant="primary" to="/data-sources">Go to Data Sources</LinkButton>}
          />
        </Card>
      ) : (
        <div className="space-y-6">
          <KpiStrip active={status} onPick={(s) => set({ status: s === "all" ? null : s, doc: null, tenant: injected ? null : undefined })} />

          <Card>
            <FilterBar onClear={clearFilters} active={hasFilters}>
              <label className="block min-w-[220px] flex-1 sm:max-w-sm">
                <span className="mb-1 block text-support text-ink-2">Search</span>
                <SearchInput value={search.input} onChange={search.setInput} placeholder="Search by document id" />
              </label>
              <FilterSelect label="Status" value={status} onChange={(v) => set({ status: v === "all" ? null : v })} options={STATUS_OPTIONS} />
              <FilterSelect label="Tenant" value={tenantFilter} onChange={(v) => set({ tenant: v || null })} options={tenantOptions} />
            </FilterBar>

            {list.isError && list.items.length === 0 ? (
              <ErrorState error={list.error} onRetry={list.refetch} />
            ) : (
              <div className={cn("transition-opacity", list.isPlaceholderData && "opacity-60")} aria-busy={list.isFetching}>
                <DataTable
                  label="Documents"
                  data={list.items}
                  columns={columns}
                  loading={list.isPending}
                  getRowId={(r) => docKey(r.tenant_id, r.document_id)}
                  activeRowId={docParam && tenantParam ? docKey(tenantParam, docParam) : null}
                  onRowClick={openDoc}
                  initialSort={[{ id: "issues", desc: true }]}
                  empty={empty}
                  note={list.total > list.items.length ? `Showing the first ${formatNumber(DOC_LIMIT)} of ${formatNumber(list.total)}. Narrow the filters.` : undefined}
                />
              </div>
            )}
          </Card>
        </div>
      )}

      {connected && docParam && tenantParam ? <DocumentDrawer key={docKey(tenantParam, docParam)} tenant={tenantParam} doc={docParam} onClose={closeDoc} /> : null}
    </>
  );
}
