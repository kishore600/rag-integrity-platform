import type { UseQueryResult } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { QueryState } from "@/components/shared/states";

/**
 * QueryState for the hooks in hooks/queries.ts. Those hooks infer their error type as `unknown` (their `retry` callback
 * takes `unknown`), while QueryState is declared for `UseQueryResult<T>` (error: `Error`), so passing them directly
 * does not typecheck. This wrapper widens the parameter and nothing else.
 */
export function QueryGate<T>({ query, skeleton, compact, children }: { query: UseQueryResult<T, unknown>; skeleton?: ReactNode; compact?: boolean; children: (data: T) => ReactNode }) {
  return (
    <QueryState query={query as unknown as UseQueryResult<T>} skeleton={skeleton} compact={compact}>
      {children}
    </QueryState>
  );
}
