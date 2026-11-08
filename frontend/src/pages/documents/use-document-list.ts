import { useMemo } from "react";
import { useDocuments, type DocumentFilters } from "@/hooks/queries";
import type { DocumentRow } from "@/types/api";

/** The status filter, plus "attention" (degraded and broken together), which the API cannot filter on in one call. */
export type DocStatusFilter = NonNullable<DocumentFilters["status"]> | "attention";
export const DOC_LIMIT = 500;

interface ListFilters {
  status: DocStatusFilter;
  tenant?: string;
  q?: string;
}

export interface DocumentList {
  items: DocumentRow[];
  total: number;
  isPending: boolean;
  isFetching: boolean;
  isPlaceholderData: boolean;
  isError: boolean;
  error: unknown;
  refetch: () => void;
}

/**
 * Documents for the table. For "attention" it reads the degraded and the broken documents with two calls and merges them
 * (each call is only enabled when needed), so the count and the rows are exact rather than filtered in the browser.
 */
export function useDocumentList(f: ListFilters, enabled = true): DocumentList {
  const attention = f.status === "attention";
  const base: DocumentFilters = { tenant: f.tenant || undefined, q: f.q || undefined, limit: DOC_LIMIT };
  const single = useDocuments({ ...base, status: attention ? undefined : (f.status as DocumentFilters["status"]) }, enabled && !attention);
  const degraded = useDocuments({ ...base, status: "degraded" }, enabled && attention);
  const broken = useDocuments({ ...base, status: "broken" }, enabled && attention);

  const mergedItems = useMemo(() => {
    if (!attention) return [];
    return [...(degraded.data?.items ?? []), ...(broken.data?.items ?? [])].sort((a, b) => b.issue_count - a.issue_count);
  }, [attention, degraded.data, broken.data]);

  if (!attention) {
    return {
      items: single.data?.items ?? [],
      total: single.data?.total ?? 0,
      isPending: single.isPending,
      isFetching: single.isFetching,
      isPlaceholderData: single.isPlaceholderData,
      isError: single.isError,
      error: single.error,
      refetch: () => void single.refetch(),
    };
  }
  return {
    items: mergedItems,
    total: (degraded.data?.total ?? 0) + (broken.data?.total ?? 0),
    isPending: degraded.isPending || broken.isPending,
    isFetching: degraded.isFetching || broken.isFetching,
    isPlaceholderData: degraded.isPlaceholderData || broken.isPlaceholderData,
    isError: degraded.isError || broken.isError,
    error: degraded.error ?? broken.error,
    refetch: () => {
      void degraded.refetch();
      void broken.refetch();
    },
  };
}
