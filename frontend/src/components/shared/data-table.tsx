import {
  flexRender,
  getCoreRowModel,
  getPaginationRowModel,
  getSortedRowModel,
  useReactTable,
  type ColumnDef,
  type RowData,
  type SortingState,
} from "@tanstack/react-table";
import { ArrowDown, ArrowUp, ChevronLeft, ChevronRight, ChevronsUpDown } from "lucide-react";
import { useState, type ReactNode } from "react";
import { cn } from "@/lib/cn";
import { Button } from "@/components/ui/button";
import { Select } from "@/components/ui/form";
import { Skeleton } from "./states";

declare module "@tanstack/react-table" {
  // Per-column styling hooks, e.g. meta: { className: "w-40 text-right" }
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  interface ColumnMeta<TData extends RowData, TValue> {
    className?: string;
  }
}

export interface DataTableProps<T> {
  data: T[];
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  columns: ColumnDef<T, any>[];
  loading?: boolean;
  getRowId?: (row: T) => string;
  onRowClick?: (row: T) => void;
  /** Highlights the row whose id matches (the one open in a drawer). */
  activeRowId?: string | null;
  /** Shown instead of rows when there are none (not while loading). */
  empty?: ReactNode;
  initialSort?: SortingState;
  pageSize?: number;
  /** Accessible table name. */
  label: string;
  skeletonRows?: number;
  /** Text under the table, e.g. "Showing the first 500 of 1,204 — narrow the filters". */
  note?: ReactNode;
}

/** Sortable, paginated table. Sorting and paging happen in the browser over the rows the page loaded (pages load up to 500). */
export function DataTable<T>({ data, columns, loading, getRowId, onRowClick, activeRowId, empty, initialSort = [], pageSize = 25, label, skeletonRows = 6, note }: DataTableProps<T>) {
  const [sorting, setSorting] = useState<SortingState>(initialSort);
  const table = useReactTable({
    data,
    columns,
    state: { sorting },
    onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getPaginationRowModel: getPaginationRowModel(),
    getRowId: getRowId ? (row) => getRowId(row) : undefined,
    initialState: { pagination: { pageSize } },
  });

  const { pageIndex, pageSize: size } = table.getState().pagination;
  const total = data.length;
  const from = total === 0 ? 0 : pageIndex * size + 1;
  const to = Math.min(total, (pageIndex + 1) * size);
  const showEmpty = !loading && total === 0 && empty;

  return (
    <div>
      {showEmpty ? (
        empty
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[640px] border-collapse text-table" aria-label={label}>
            <thead>
              {table.getHeaderGroups().map((hg) => (
                <tr key={hg.id} className="border-b border-line bg-app">
                  {hg.headers.map((h) => {
                    const sortable = h.column.getCanSort();
                    const dir = h.column.getIsSorted();
                    return (
                      <th
                        key={h.id}
                        scope="col"
                        aria-sort={dir === "asc" ? "ascending" : dir === "desc" ? "descending" : undefined}
                        className={cn("table-head whitespace-nowrap px-3 py-2.5 text-left first:pl-4 last:pr-4", h.column.columnDef.meta?.className)}
                      >
                        {h.isPlaceholder ? null : sortable ? (
                          <button type="button" onClick={h.column.getToggleSortingHandler()} className="inline-flex items-center gap-1 rounded uppercase tracking-wide hover:text-ink">
                            {flexRender(h.column.columnDef.header, h.getContext())}
                            {dir === "asc" ? <ArrowUp className="h-3 w-3" aria-hidden /> : dir === "desc" ? <ArrowDown className="h-3 w-3" aria-hidden /> : <ChevronsUpDown className="h-3 w-3 text-ink-3" aria-hidden />}
                          </button>
                        ) : (
                          flexRender(h.column.columnDef.header, h.getContext())
                        )}
                      </th>
                    );
                  })}
                </tr>
              ))}
            </thead>
            <tbody>
              {loading
                ? Array.from({ length: skeletonRows }).map((_, r) => (
                    <tr key={r} className="border-b border-line last:border-0">
                      {table.getAllLeafColumns().map((c) => (
                        <td key={c.id} className="px-3 py-3.5 first:pl-4 last:pr-4">
                          <Skeleton className="h-4 w-full max-w-[160px]" />
                        </td>
                      ))}
                    </tr>
                  ))
                : table.getRowModel().rows.map((row) => {
                    const active = activeRowId != null && row.id === activeRowId;
                    return (
                      <tr
                        key={row.id}
                        onClick={onRowClick ? () => onRowClick(row.original) : undefined}
                        onKeyDown={
                          onRowClick
                            ? (e) => {
                                if (e.key === "Enter" || e.key === " ") {
                                  e.preventDefault();
                                  onRowClick(row.original);
                                }
                              }
                            : undefined
                        }
                        tabIndex={onRowClick ? 0 : undefined}
                        className={cn("border-b border-line last:border-0", onRowClick && "cursor-pointer hover:bg-surface-hover focus-visible:bg-surface-hover", active && "bg-brand-light/60 hover:bg-brand-light/60")}
                      >
                        {row.getVisibleCells().map((cell) => (
                          <td key={cell.id} className={cn("px-3 py-3 align-middle text-ink first:pl-4 last:pr-4", cell.column.columnDef.meta?.className)}>
                            {flexRender(cell.column.columnDef.cell, cell.getContext())}
                          </td>
                        ))}
                      </tr>
                    );
                  })}
            </tbody>
          </table>
        </div>
      )}

      {!showEmpty && !loading && total > 0 ? (
        <div className="flex flex-wrap items-center justify-between gap-3 border-t border-line px-4 py-3 text-support text-ink-2">
          <div>
            Showing <span className="font-medium text-ink">{from}–{to}</span> of <span className="font-medium text-ink">{total}</span>
            {note ? <span className="ml-2">{note}</span> : null}
          </div>
          <div className="flex items-center gap-3">
            <label className="flex items-center gap-2">
              Rows
              <Select aria-label="Rows per page" value={size} onChange={(e) => table.setPageSize(Number(e.target.value))} className="h-8 w-[72px] py-0 text-support">
                {[10, 25, 50, 100].map((n) => (
                  <option key={n} value={n}>{n}</option>
                ))}
              </Select>
            </label>
            <div className="flex items-center gap-1">
              <Button variant="secondary" size="icon-sm" onClick={() => table.previousPage()} disabled={!table.getCanPreviousPage()} aria-label="Previous page">
                <ChevronLeft className="h-4 w-4" />
              </Button>
              <span className="min-w-[72px] text-center tabular-nums">Page {pageIndex + 1} of {Math.max(1, table.getPageCount())}</span>
              <Button variant="secondary" size="icon-sm" onClick={() => table.nextPage()} disabled={!table.getCanNextPage()} aria-label="Next page">
                <ChevronRight className="h-4 w-4" />
              </Button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
