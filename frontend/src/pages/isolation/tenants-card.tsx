import type { ColumnDef } from "@tanstack/react-table";
import { SearchX, Users } from "lucide-react";
import { useMemo } from "react";
import { useNavigate } from "react-router-dom";
import { Badge } from "@/components/ui/badge";
import { Card, CardHeader } from "@/components/ui/card";
import { SearchInput } from "@/components/ui/form";
import { DataTable } from "@/components/shared/data-table";
import { FilterBar } from "@/components/shared/filters";
import { EmptyState } from "@/components/shared/states";
import { cn } from "@/lib/cn";
import { formatNumber, formatPercent } from "@/lib/format";
import { links } from "@/lib/links";
import type { IsolationTenant } from "@/types/api";
import { TENANT_STATUS } from "./meta";
import { useUrlSearch } from "./use-url-search";

function StatusCell({ t, limited }: { t: IsolationTenant; limited: boolean }) {
  // while the check is limited, "clean" would claim more than was looked at
  if (limited && t.status === "clean") return <Badge tone="neutral" dot>Not fully checked</Badge>;
  const s = TENANT_STATUS[t.status];
  return <Badge tone={s.tone} dot>{s.label}</Badge>;
}

const Pct = ({ value }: { value: number | null }) => (
  <span className={cn("whitespace-nowrap", value !== null && value < 100 && "font-medium text-warning")}>{formatPercent(value)}</span>
);

/** A count that is quiet at zero and loud when it is not. */
const Count = ({ n, tone }: { n: number; tone: "critical" | "warning" }) =>
  n > 0 ? <span className={cn("font-medium", tone === "critical" ? "text-critical" : "text-warning")}>{formatNumber(n)}</span> : <span className="text-ink-3">0</span>;

function buildColumns(limited: boolean): ColumnDef<IsolationTenant>[] {
  return [
    {
      id: "tenant",
      header: "Tenant",
      accessorFn: (t) => t.tenant_id,
      cell: ({ row }) => (
        <span className="block max-w-[220px] truncate font-medium text-ink" title={row.original.tenant_id}>
          {row.original.tenant_id}
        </span>
      ),
    },
    {
      id: "status",
      header: "Status",
      accessorFn: (t) => TENANT_STATUS[t.status].rank,
      cell: ({ row }) => <StatusCell t={row.original} limited={limited} />,
    },
    { id: "documents", header: "Documents", accessorFn: (t) => t.documents, meta: { className: "text-right tabular-nums" }, cell: ({ row }) => formatNumber(row.original.documents) },
    { id: "points", header: "Vectors", accessorFn: (t) => t.points, meta: { className: "text-right tabular-nums" }, cell: ({ row }) => formatNumber(row.original.points) },
    {
      id: "tenant_label",
      header: () => <span title="Share of this tenant's vectors that carry a tenant label">Tenant label</span>,
      accessorFn: (t) => t.tenant_label_pct ?? -1,
      meta: { className: "text-right tabular-nums" },
      cell: ({ row }) => <Pct value={row.original.tenant_label_pct} />,
    },
    {
      id: "permission_label",
      header: () => <span title="Share of this tenant's vectors that carry a permission label">Permission label</span>,
      accessorFn: (t) => t.permission_label_pct ?? -1,
      meta: { className: "text-right tabular-nums" },
      cell: ({ row }) =>
        row.original.permission_label_pct === null ? (
          <span className="whitespace-nowrap text-ink-3" title="Your index does not record permissions">
            Not recorded
          </span>
        ) : (
          <Pct value={row.original.permission_label_pct} />
        ),
    },
    {
      id: "foreign",
      header: () => <span title="Documents that belong to another tenant but are indexed under this one">Foreign documents</span>,
      accessorFn: (t) => t.foreign_documents,
      meta: { className: "text-right tabular-nums" },
      cell: ({ row }) => <Count n={row.original.foreign_documents} tone="critical" />,
    },
    {
      id: "permission_mismatch",
      header: () => <span title="Documents whose vectors carry a permission hash that differs from the manifest">Permission mismatch</span>,
      accessorFn: (t) => t.permission_mismatch_documents,
      meta: { className: "text-right tabular-nums" },
      cell: ({ row }) => <Count n={row.original.permission_mismatch_documents} tone="warning" />,
    },
  ];
}

const TITLE = "Tenants";
const DESCRIPTION = "Worst first. Select a tenant to see its documents.";

export function TenantsSkeleton() {
  return (
    <Card>
      <CardHeader title={TITLE} description={DESCRIPTION} />
      <DataTable label="Loading tenants" data={[]} columns={buildColumns(false)} loading skeletonRows={4} />
    </Card>
  );
}

/** Every tenant the last full audit saw, worst first. A row opens that tenant's documents. */
export function TenantsCard({ tenants, total, limited }: { tenants: IsolationTenant[]; total: number; limited: boolean }) {
  const navigate = useNavigate();
  const search = useUrlSearch("q");
  const columns = useMemo(() => buildColumns(limited), [limited]);

  const needle = search.text.trim().toLowerCase();
  const rows = useMemo(() => (needle ? tenants.filter((t) => t.tenant_id.toLowerCase().includes(needle)) : tenants), [tenants, needle]);
  const cut = total > tenants.length;

  return (
    <Card>
      <CardHeader title={TITLE} description={DESCRIPTION} />
      {tenants.length > 0 ? (
        <FilterBar onClear={() => search.setText("")} active={!!search.text}>
          <label className="block min-w-[220px] flex-1 sm:max-w-sm">
            <span className="mb-1 block text-support text-ink-2">Search</span>
            <SearchInput value={search.text} onChange={search.setText} placeholder="Search tenants" />
          </label>
        </FilterBar>
      ) : null}
      {cut ? (
        <p className="border-b border-line bg-app px-4 py-2 text-support text-ink-2">
          Showing the worst {formatNumber(tenants.length)} of {formatNumber(total)} tenants.
        </p>
      ) : null}
      <DataTable
        label="Tenants"
        data={rows}
        columns={columns}
        getRowId={(t) => t.tenant_id}
        onRowClick={(t) => navigate(links.documents({ tenant: t.tenant_id }))}
        initialSort={[{ id: "status", desc: false }]}
        empty={
          needle ? (
            <EmptyState compact icon={SearchX} title="No tenants match" description="Try a different search." />
          ) : (
            <EmptyState compact icon={Users} title="No tenants found" description="The last full audit found no documents or vectors, so there are no tenants to list." />
          )
        }
      />
    </Card>
  );
}
