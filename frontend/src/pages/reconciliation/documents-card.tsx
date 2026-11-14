import type { ColumnDef } from "@tanstack/react-table";
import { Check, FileSearch, X } from "lucide-react";
import { useMemo } from "react";
import { useNavigate } from "react-router-dom";
import { Card, CardHeader } from "@/components/ui/card";
import { SearchInput } from "@/components/ui/form";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/menus";
import { DataTable } from "@/components/shared/data-table";
import { FilterBar, FilterSelect } from "@/components/shared/filters";
import { DocStateBadge, SeverityBadge } from "@/components/shared/status";
import { EmptyState, ErrorState } from "@/components/shared/states";
import { useDocuments, useManifestConnected } from "@/hooks/queries";
import { cn } from "@/lib/cn";
import { documentName, formatNumber } from "@/lib/format";
import { links } from "@/lib/links";
import type { DocumentRow, TenantHealth } from "@/types/api";
import { useClearParams, useUrlParam, useUrlSearch } from "./use-url-state";

const LIMIT = 500;

type View = "all" | "healthy" | "attention" | "orphaned" | "pending";
const VIEWS: { id: View; label: string; match: (d: DocumentRow) => boolean }[] = [
  { id: "all", label: "All", match: () => true },
  { id: "healthy", label: "Healthy", match: (d) => d.status === "healthy" },
  { id: "attention", label: "Needs attention", match: (d) => d.status === "degraded" || d.status === "broken" },
  { id: "orphaned", label: "Orphaned", match: (d) => d.status === "orphaned" },
  { id: "pending", label: "Pending", match: (d) => d.status === "pending" },
];

function Presence({ doc }: { doc: DocumentRow }) {
  const manifestConnected = useManifestConnected(); // with no manifest connected there is nothing to be present in
  const places: [string, number][] = [
    ["Source", doc.source_present],
    ...(manifestConnected ? ([["Manifest", doc.manifest_present]] as [string, number][]) : []),
    ["Index", doc.index_present],
  ];
  return (
    <div className="flex items-center gap-1.5">
      {places.map(([label, present]) => {
        const text = `${label}: ${present ? "present" : "missing"}`;
        return (
          <span
            key={label}
            role="img"
            aria-label={text}
            title={text}
            className={cn("flex h-5 w-5 items-center justify-center rounded-full", present ? "bg-success-bg text-success" : "bg-critical-bg text-critical")}
          >
            {present ? <Check className="h-3 w-3" aria-hidden /> : <X className="h-3 w-3" aria-hidden />}
          </span>
        );
      })}
    </div>
  );
}

const columns: ColumnDef<DocumentRow>[] = [
  {
    id: "document",
    header: "Document",
    accessorFn: (d) => d.document_id,
    cell: ({ row }) => {
      const id = row.original.document_id;
      const name = documentName(id);
      return (
        <div className="min-w-0 max-w-[340px]">
          <p className="truncate font-medium text-ink" title={id}>
            {name}
          </p>
          {name !== id ? (
            <p className="truncate text-support text-ink-2" title={id}>
              {id}
            </p>
          ) : null}
        </div>
      );
    },
  },
  {
    id: "tenant",
    header: "Tenant",
    accessorFn: (d) => d.tenant_id,
    cell: ({ row }) => (
      <span className="block max-w-[160px] truncate text-ink-2" title={row.original.tenant_id}>
        {row.original.tenant_id}
      </span>
    ),
  },
  { id: "status", header: "Status", accessorFn: (d) => d.status, cell: ({ row }) => <DocStateBadge doc={row.original} /> },
  { id: "presence", header: "Where it exists", enableSorting: false, cell: ({ row }) => <Presence doc={row.original} /> },
  {
    id: "chunks",
    header: "Chunks",
    accessorFn: (d) => d.indexed_chunks,
    meta: { className: "text-right tabular-nums" },
    cell: ({ row }) => {
      const { indexed_chunks: have, expected_chunks: want } = row.original;
      const short = want !== null && have < want;
      return (
        <span className={cn("whitespace-nowrap", short && "font-medium text-warning")} title={want === null ? "The manifest does not record an expected count" : `${have} indexed of ${want} expected`}>
          {formatNumber(have)} / {want === null ? "—" : formatNumber(want)}
        </span>
      );
    },
  },
  {
    id: "issues",
    header: "Issues",
    accessorFn: (d) => d.issue_count,
    meta: { className: "text-right" },
    cell: ({ row }) =>
      row.original.issue_count > 0 ? (
        <div className="flex items-center justify-end gap-2">
          <span className="tabular-nums text-ink">{formatNumber(row.original.issue_count)}</span>
          <SeverityBadge severity={row.original.worst_severity} />
        </div>
      ) : (
        <span className="tabular-nums text-ink-3">0</span>
      ),
  },
];

/** Every document the last audit knows about, with where it is present and what is wrong with it. */
export function DocumentsCard({ tenants }: { tenants: TenantHealth[] }) {
  const navigate = useNavigate();
  const [view, setView] = useUrlParam("view", "all");
  const [tenant, setTenant] = useUrlParam("tenant");
  const search = useUrlSearch("q");
  const clearParams = useClearParams();

  const q = useDocuments({ limit: LIMIT, tenant: tenant || undefined, q: search.value || undefined });
  const items = useMemo(() => q.data?.items ?? [], [q.data]);

  const counts = useMemo(() => Object.fromEntries(VIEWS.map((v) => [v.id, items.filter(v.match).length])) as Record<View, number>, [items]);
  const active = VIEWS.find((v) => v.id === view) ?? VIEWS[0];
  const rows = useMemo(() => items.filter(active.match), [items, active]);

  const tenantOptions = useMemo(() => {
    const ids = tenants.map((t) => t.tenant_id);
    if (tenant && !ids.includes(tenant)) ids.push(tenant);
    return [{ value: "", label: "All tenants" }, ...ids.map((id) => ({ value: id, label: id }))];
  }, [tenants, tenant]);

  const filtered = !!(tenant || search.text || active.id !== "all");
  function clear() {
    clearParams(["tenant", "view", "q"]);
    search.setText("");
  }

  const total = q.data?.total ?? 0;
  const loaded = q.data?.items.length ?? 0;

  return (
    <Card>
      <CardHeader title="Documents" description="Every document the last audit compared, and where it was found." />
      <Tabs value={active.id} onValueChange={setView}>
        <TabsList className="px-3" aria-label="Filter documents by status">
          {VIEWS.map((v) => (
            <TabsTrigger key={v.id} value={v.id}>
              {v.label}
              <span className="rounded-full bg-surface px-1.5 text-support tabular-nums text-ink-2">{q.data ? formatNumber(counts[v.id]) : "·"}</span>
            </TabsTrigger>
          ))}
        </TabsList>
        <FilterBar onClear={clear} active={filtered}>
          <div className="min-w-[220px] flex-1 sm:max-w-sm">
            <span className="mb-1 block text-support text-ink-2">Search</span>
            <SearchInput value={search.text} onChange={search.setText} placeholder="Search documents" />
          </div>
          <FilterSelect label="Tenant" value={tenant} onChange={setTenant} options={tenantOptions} />
        </FilterBar>
        <TabsContent value={active.id} className="pt-0">
          {q.isError ? (
            <ErrorState error={q.error} onRetry={() => void q.refetch()} />
          ) : (
            <div className={cn(q.isPlaceholderData && "opacity-60 transition-opacity")} aria-busy={q.isFetching}>
              <DataTable
                label="Documents"
                data={rows}
                columns={columns}
                loading={q.isPending}
                getRowId={(d) => `${d.tenant_id}/${d.document_id}`}
                onRowClick={(d) => navigate(links.document(d.tenant_id, d.document_id))}
                initialSort={[{ id: "issues", desc: true }]}
                note={total > loaded ? `Loaded the first ${formatNumber(loaded)} of ${formatNumber(total)}. Narrow the filters to see the rest.` : undefined}
                empty={
                  filtered ? (
                    <EmptyState compact icon={FileSearch} title="No documents match" description="Try a different search or clear the filters." />
                  ) : (
                    <EmptyState icon={FileSearch} title="No documents yet" description="Documents appear here after the first audit finds them in your source, manifest or index." />
                  )
                }
              />
            </div>
          )}
        </TabsContent>
      </Tabs>
    </Card>
  );
}
