/**
 * Every server call the UI makes lives here, typed against src/types/api.ts. Pages import these hooks and never call fetch.
 * Mutations invalidate the cached reads they affect, so the screen always reflects the real backend state.
 */
import { keepPreviousData, useMutation, useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";
import { ApiError, del, get, post, put, qs } from "@/lib/api";
import type {
  ApiKey,
  AuditRequest,
  AuditRun,
  AuditStartResponse,
  BlastRadius,
  BlastScenario,
  ConnectionStatus,
  CreatedApiKey,
  DocumentDetail,
  DocumentRow,
  DrillRequest,
  DrillResult,
  HistoryEvent,
  IsolationView,
  IssueDetail,
  Issue,
  Overview,
  Paged,
  PlanRequest,
  Recommendations,
  RepairPlan,
  Session,
  SettingsKind,
  SettingsView,
  TestResult,
} from "@/types/api";

export const qk = {
  session: ["session"] as const,
  overview: ["overview"] as const,
  connections: ["connections"] as const,
  settings: ["settings"] as const,
  keys: ["keys"] as const,
  repairs: ["repairs"] as const,
};

/** Refresh every cached read that depends on audit results (not the session or the saved settings). */
export function invalidateData(qc: QueryClient): Promise<void> {
  return qc.invalidateQueries({ predicate: (q) => q.queryKey[0] !== "session" && q.queryKey[0] !== "settings" && q.queryKey[0] !== "keys" });
}

const noRetryOnClientError = (count: number, err: unknown): boolean => !(err instanceof ApiError && err.status >= 400 && err.status < 500) && count < 2;

// ---- session -------------------------------------------------------------------------------------------
export const useSession = () => useQuery({ queryKey: qk.session, queryFn: () => get<Session>("/api/session"), staleTime: 60_000, retry: 1 });

// ---- overview & connections ------------------------------------------------------------------------------
export const useOverview = (enabled = true) =>
  useQuery({
    queryKey: qk.overview,
    queryFn: () => get<Overview>("/api/overview"),
    enabled,
    retry: noRetryOnClientError,
    // while an audit is running, follow it; otherwise the numbers only change when the user acts
    refetchInterval: (q) => (q.state.data?.audit_running ? 3000 : false),
  });

export const useConnections = (enabled = true) =>
  useQuery({ queryKey: qk.connections, queryFn: () => get<ConnectionStatus[]>("/api/connections"), enabled, retry: noRetryOnClientError, staleTime: 30_000 });

// ---- audits ------------------------------------------------------------------------------------------------
export const useAudits = (limit = 30) =>
  useQuery({ queryKey: ["audits", limit], queryFn: () => get<AuditRun[]>(`/api/audits${qs({ limit })}`), retry: noRetryOnClientError, placeholderData: keepPreviousData });

export const useAudit = (runId: string | undefined) =>
  useQuery({
    queryKey: ["audit", runId],
    queryFn: () => get<AuditRun>(`/api/audits/${encodeURIComponent(runId ?? "")}`),
    enabled: !!runId,
    retry: noRetryOnClientError,
    refetchInterval: (q) => (q.state.data?.status === "running" ? 3000 : false),
  });

export function useStartAudit() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (req: AuditRequest = {}) => post<AuditStartResponse>("/api/audits", req),
    onSettled: () => invalidateData(qc),
  });
}

// ---- issues ------------------------------------------------------------------------------------------------
export interface IssueFilters {
  status?: "open" | "resolved" | "ignored" | "all";
  severity?: string;
  type?: string;
  tenant?: string;
  q?: string;
  limit?: number;
  offset?: number;
}

export const useIssues = (f: IssueFilters = {}, enabled = true) =>
  useQuery({
    queryKey: ["issues", f],
    queryFn: () => get<Paged<Issue>>(`/api/issues${qs({ ...f })}`),
    enabled,
    retry: noRetryOnClientError,
    placeholderData: keepPreviousData,
  });

export const useIssue = (id: string | undefined) =>
  useQuery({ queryKey: ["issue", id], queryFn: () => get<IssueDetail>(`/api/issues/${encodeURIComponent(id ?? "")}`), enabled: !!id, retry: noRetryOnClientError });

export function useIgnoreIssue() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, reason }: { id: string; reason?: string }) => post<{ ok: boolean }>(`/api/issues/${encodeURIComponent(id)}/ignore`, { reason: reason || null }),
    onSuccess: () => invalidateData(qc),
  });
}

export function useReopenIssue() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => post<{ ok: boolean }>(`/api/issues/${encodeURIComponent(id)}/reopen`),
    onSuccess: () => invalidateData(qc),
  });
}

// ---- documents ----------------------------------------------------------------------------------------------
export interface DocumentFilters {
  status?: "healthy" | "degraded" | "broken" | "pending" | "orphaned" | "all";
  tenant?: string;
  q?: string;
  limit?: number;
  offset?: number;
}

export const useDocuments = (f: DocumentFilters = {}, enabled = true) =>
  useQuery({
    queryKey: ["documents", f],
    queryFn: () => get<Paged<DocumentRow>>(`/api/documents${qs({ ...f })}`),
    enabled,
    retry: noRetryOnClientError,
    placeholderData: keepPreviousData,
  });

/** `live` re-reads the document from S3, the manifest and Qdrant right now (slower, but the truth). */
export const useDocument = (tenant: string | undefined, documentId: string | undefined, live = false) =>
  useQuery({
    queryKey: ["document", tenant, documentId, live],
    queryFn: () => get<DocumentDetail>(`/api/document${qs({ tenant, document_id: documentId, live })}`),
    enabled: !!tenant && !!documentId,
    retry: noRetryOnClientError,
  });

// ---- history ------------------------------------------------------------------------------------------------
export const useHistory = (limit = 100) =>
  useQuery({ queryKey: ["history", limit], queryFn: () => get<HistoryEvent[]>(`/api/history${qs({ limit })}`), retry: noRetryOnClientError, placeholderData: keepPreviousData });

// ---- repairs, recommendations, impact --------------------------------------------------------------------------
export const useRecommendations = (minSeverity?: string) =>
  useQuery({ queryKey: ["recommendations", minSeverity ?? ""], queryFn: () => get<Recommendations>(`/api/recommendations${qs({ min_severity: minSeverity })}`), retry: noRetryOnClientError });

export const useRepairs = () => useQuery({ queryKey: qk.repairs, queryFn: () => get<RepairPlan[]>("/api/repairs"), retry: noRetryOnClientError });

export const useRepairPlan = (id: string | undefined) =>
  useQuery({ queryKey: ["repair", id], queryFn: () => get<RepairPlan>(`/api/repairs/${encodeURIComponent(id ?? "")}`), enabled: !!id, retry: noRetryOnClientError });

function useRepairMutation<V>(fn: (v: V) => Promise<RepairPlan>) {
  const qc = useQueryClient();
  return useMutation({ mutationFn: fn, onSettled: () => invalidateData(qc) });
}

export const useCreatePlan = () => useRepairMutation((req: PlanRequest) => post<RepairPlan>("/api/repairs", req));
export const useTriggerPlan = () => useRepairMutation((id: string) => post<RepairPlan>(`/api/repairs/${encodeURIComponent(id)}/trigger`));
export const useVerifyPlan = () => useRepairMutation((id: string) => post<RepairPlan>(`/api/repairs/${encodeURIComponent(id)}/verify`));
export const useApproveCleanup = () => useRepairMutation((id: string) => post<RepairPlan>(`/api/repairs/${encodeURIComponent(id)}/approve-cleanup`));

export const useBlastRadius = () => useMutation({ mutationFn: (scenario: BlastScenario) => post<BlastRadius>("/api/blast-radius", { scenario }) });

// ---- settings & API keys (multi-user app mode) -----------------------------------------------------------------
export const useSettings = (enabled = true) =>
  useQuery({ queryKey: qk.settings, queryFn: () => get<SettingsView>("/api/settings"), enabled, retry: noRetryOnClientError, staleTime: 30_000 });

export function useSaveSettings() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ kind, values }: { kind: SettingsKind; values: Record<string, unknown> }) => put<SettingsView>(`/api/settings/${kind}`, { values }),
    onSuccess: (view) => {
      qc.setQueryData(qk.settings, view);
      // connection settings change what the whole product reads: session.ready, overview, connection health
      void qc.invalidateQueries({ queryKey: qk.session });
      void invalidateData(qc);
    },
  });
}

/** Test a group. With `values` it tests what is typed in the form without saving it; without, it tests (and remembers) the saved settings. */
export function useTestSettings() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ kind, values }: { kind: SettingsKind; values?: Record<string, unknown> }) =>
      post<TestResult>(`/api/settings/${kind}/test`, values === undefined ? undefined : { values }),
    onSuccess: (_r, v) => {
      if (v.values === undefined) {
        void qc.invalidateQueries({ queryKey: qk.settings });
        void qc.invalidateQueries({ queryKey: qk.connections });
      }
    },
  });
}

export const useApiKeys = (enabled = true) => useQuery({ queryKey: qk.keys, queryFn: () => get<ApiKey[]>("/api/keys"), enabled, retry: noRetryOnClientError });

export function useCreateApiKey() {
  const qc = useQueryClient();
  return useMutation({ mutationFn: (name: string) => post<CreatedApiKey>("/api/keys", { name }), onSuccess: () => qc.invalidateQueries({ queryKey: qk.keys }) });
}

export function useRevokeApiKey() {
  const qc = useQueryClient();
  return useMutation({ mutationFn: (id: string) => del<{ ok: boolean }>(`/api/keys/${encodeURIComponent(id)}`), onSuccess: () => qc.invalidateQueries({ queryKey: qk.keys }) });
}

export function useChangePassword() {
  return useMutation({ mutationFn: (v: { current_password: string; new_password: string }) => post<{ ok: boolean }>("/api/auth/password", v) });
}

// ---- tenant isolation ------------------------------------------------------------------------------------------
/** The isolation picture of the latest full audit. It only changes when an audit finishes (invalidateData refreshes it), so it is not polled. */
export const useIsolation = (enabled = true) =>
  useQuery({ queryKey: ["isolation"], queryFn: () => get<IsolationView>("/api/isolation"), enabled, retry: noRetryOnClientError });

/** The read-only fire drill. It changes nothing on the server, so it deliberately does not invalidate any cached read. */
export const useIsolationDrill = () => useMutation({ mutationFn: (req: DrillRequest = {}) => post<DrillResult>("/api/isolation/drill", req) });
