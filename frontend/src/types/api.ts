/** Types for the RAGGuard backend API. They mirror the Python responses exactly (src/ragintegrity/api/app.py). */

export type Severity = "critical" | "high" | "medium" | "low" | "info";
export type IssueStatus = "open" | "resolved" | "ignored";
export type DocumentStatus = "healthy" | "degraded" | "broken" | "pending" | "orphaned";

export type IssueType =
  | "missing_embedding"
  | "partial_index"
  | "stale_embedding"
  | "superseded_active"
  | "orphan_vector"
  | "duplicate_chunk"
  | "metadata_inconsistent"
  | "pipeline_drift"
  | "empty_embedding"
  | "tenant_mismatch"
  | "manifest_orphan";

export type RepairAction = "reindex_full" | "reindex_chunks" | "cleanup_vectors" | "fix_metadata" | "investigate";

export interface Session {
  app: boolean; // true = multi-user app mode (sign-in required)
  mode: string; // app | live | demo
  version: string;
  authenticated: boolean;
  registration_open?: boolean;
  setup?: { required: boolean; problems?: string[] };
  user?: { email: string } | null;
  workspace?: { name: string };
  ready?: boolean; // all three required connections are configured
  demo?: boolean; // single-user demo backend (synthetic data)
  api_key_required?: boolean;
}

export interface AuditStats {
  source_documents?: number;
  manifest_rows?: number;
  index_points?: number;
  documents_total?: number;
  documents_by_status?: Record<string, number>;
  findings_total?: number;
  findings_by_type?: Record<string, number>;
  findings_by_severity?: Record<string, number>;
  health_score?: number;
  duration_seconds?: number;
  retrieval_probes?: number;
  diff?: { opened: number; reopened: number; escalated: number; resolved: number; unchanged: number };
  scope?: { tenant?: string; documents?: number };
  alerts?: { sent?: number; issues?: number; reason?: string; error?: string };
}

export interface AuditRun {
  id: string;
  workspace_id: string;
  kind: "full" | "scoped" | "verify";
  trigger: string;
  scope: { tenant?: string; documents?: number };
  status: "running" | "completed" | "failed";
  started_at: string;
  finished_at: string | null;
  stats: AuditStats;
  error: string | null;
}

export interface TenantHealth {
  tenant_id: string;
  documents: number;
  healthy: number;
  health_score: number | null;
}

export interface Overview {
  mode: string;
  demo: boolean;
  documents: { total: number; by_status: Record<string, number>; health_score: number | null; tenants: TenantHealth[] };
  issues: { open: number; by_severity: Record<Severity, number>; by_type: Record<string, number>; resolved: number; ignored: number };
  latest_run: AuditRun | null;
  latest_full_run: AuditRun | null;
  trend: { at: string | null; health_score: number | null; findings: number | null; documents: number | null }[];
  audit_running: boolean;
  query_log_size: number;
  target_fingerprint: Record<string, string | number> | null;
  scheduler_interval_minutes: number;
  cleanup_policy: string;
  repair_webhook_configured: boolean;
}

/** Evidence differs per issue type; see lib/issue-meta.ts for how it is read. */
export type Evidence = Record<string, unknown> & {
  retrieval_probe?: {
    reachable?: boolean;
    rank?: number | null;
    top_k?: number;
    score?: number | null;
    tenant_filter?: string;
    method?: string;
    results?: { rank: number; document_id: string | null; score: number; is_stale_content: boolean }[];
    error?: string;
  };
  problems?: { code: string; severity: string; message: string }[];
  removal_points?: Record<string, string[]>;
  removal_count?: number;
  missing_chunks?: string[];
  pipeline_reported_success?: boolean;
};

export interface Issue {
  workspace_id: string;
  id: string;
  type: IssueType;
  severity: Severity;
  status: IssueStatus;
  tenant_id: string;
  document_id: string;
  collection: string | null;
  title: string;
  detail: string;
  evidence: Evidence;
  action: RepairAction;
  first_seen_at: string;
  last_seen_at: string;
  first_run_id: string;
  last_run_id: string;
  resolved_at: string | null;
  resolved_run_id: string | null;
  occurrences: number;
  reopened_count: number;
  ignored_reason: string | null;
}

export interface IssueEvent {
  id: number;
  issue_id: string;
  run_id: string | null;
  ts: string;
  event: string;
  details: Record<string, unknown>;
}

export interface IssueDetail extends Issue {
  events: IssueEvent[];
}

export interface Paged<T> {
  total: number;
  items: T[];
}

export interface DocumentRow {
  tenant_id: string;
  document_id: string;
  status: DocumentStatus;
  issue_count: number;
  worst_severity: Severity | null;
  issue_types: IssueType[];
  fingerprint: Record<string, string | number>;
  source_uri: string | null;
  source_hash: string | null;
  source_version: string | null;
  indexed_version: string | null;
  size_bytes: number;
  expected_chunks: number | null;
  indexed_chunks: number;
  manifest_status: string | null;
  manifest_updated_at: string | null;
  collections: string[];
  source_present: number;
  manifest_present: number;
  index_present: number;
  last_verified_at: string;
  last_run_id: string;
}

export interface LiveSnapshot {
  tenant_id: string;
  document_id: string;
  status: string;
  source: { source_uri: string; source_version: string | null; source_hash: string | null; size_bytes: number; last_modified: string | null; hash_reliable: boolean } | null;
  manifest: {
    processing_status: string | null;
    source_hash: string | null;
    source_version: string | null;
    indexed_version: string | null;
    expected_chunk_count: number | null;
    indexed_chunk_count: number | null;
    updated_at: string | null;
    fingerprint: Record<string, string | number>;
  } | null;
  expected_chunks: { chunk_id: string; chunk_index: number | null; chunk_hash: string | null }[];
  index: {
    points: number;
    by_class: Record<string, number>;
    collections: string[];
    fingerprints: Record<string, string | number>[];
    chunks: { collection: string; chunk_id: string; chunk_index: number | null; class: string; copies: number; point_ids: string[] }[];
    chunks_truncated: boolean;
  };
  findings: { id: string; type: IssueType; severity: Severity; title: string; detail: string; action: RepairAction }[];
}

export interface DocumentDetail {
  document: DocumentRow | null;
  issues: Issue[];
  live?: LiveSnapshot;
}

export type HistoryEvent =
  | { kind: "issue"; ts: string; event: string; issue_id: string; run_id: string | null; title: string; severity: Severity; tenant_id: string; document_id: string; type: IssueType; details: Record<string, unknown> }
  | { kind: "repair"; ts: string; event: string; plan_id: string; details: Record<string, unknown> }
  | { kind: "audit"; ts: string; event: string; run_id: string; details: { kind: string; trigger: string; scope: Record<string, unknown>; findings: number | null; health_score: number | null; error: string | null } };

export interface RepairItem {
  tenant_id: string;
  document_id: string;
  actions: RepairAction[];
  cleanup: boolean;
  cleanup_vectors: number;
  issue_ids: string[];
  issue_types: IssueType[];
  worst_severity: Severity;
  source_uri: string | null;
  expected_chunk_count: number | null;
  missing_count: number;
  missing_chunks: string[];
  collections: string[];
  status: string;
  checks: Record<string, boolean>;
  remaining_types: IssueType[];
}

export interface WorkloadSummary {
  documents_affected: number;
  documents_to_reprocess: number;
  full_reindex_documents: number;
  chunk_reindex_documents: number;
  metadata_fix_documents: number;
  cleanup_documents: number;
  vectors_to_remove: number;
  chunks_to_regenerate: number;
  embeddings_to_update: number;
  estimated_tokens: number;
  estimated_cost_usd: number;
  collections_affected: string[];
  tenants_affected: string[];
  by_tenant: { tenant_id: string; documents: number; chunks: number }[];
  full_corpus: { documents: number; chunks: number; estimated_tokens: number; estimated_cost_usd: number };
  savings_vs_full_reindex_pct: number | null;
  assumptions: string;
}

export interface RepairEvent {
  id: number;
  plan_id: string;
  ts: string;
  event: string;
  details: Record<string, unknown>;
}

export interface RepairPlan {
  id: string;
  status: "draft" | "triggered" | "partial" | "failed" | "cleanup_pending" | "cleanup_triggered" | "completed";
  created_at: string;
  updated_at: string;
  items: RepairItem[];
  summary: WorkloadSummary;
  events?: RepairEvent[];
}

export interface Recommendations {
  summary: WorkloadSummary;
  items: RepairItem[];
  items_truncated: boolean;
}

export interface BlastRadius {
  scenario: { type: string; [k: string]: unknown };
  description: string;
  documents: { affected: number; confirmed: number; total: number; affected_pct: number };
  tenants: { tenant_id: string; affected: number; total: number }[];
  collections: string[];
  by_issue_type: Record<string, number>;
  queries: {
    queries_in_window: number;
    affected_queries: number;
    affected_pct: number | null;
    top_documents: { tenant_id: string; document_id: string; queries: number }[];
    window_days: number;
    note: string | null;
  };
  workload: WorkloadSummary;
  sample: { tenant_id: string; document_id: string; status: string; confirmed: boolean }[];
}

// ---- settings (connections) --------------------------------------------------------------------------
export type SettingsKind = "s3" | "manifest" | "qdrant" | "pipeline" | "repair" | "alerts" | "policy";
export type FieldType = "str" | "int" | "float" | "bool" | "enum" | "url" | "pgurl" | "json" | "ident" | "regex" | "csv";

export interface SettingsField {
  name: string;
  label: string;
  type: FieldType;
  secret: boolean;
  required: boolean;
  help: string;
  placeholder: string;
  choices: string[];
  value: string | number | boolean | null; // never set for secret fields
  has_value: boolean; // for secret fields: a value is stored (it is never returned)
}

export interface CheckResult {
  name: string;
  status: "ok" | "warn" | "fail";
  detail: string;
}

export interface TestResult {
  ok: boolean;
  tested_at: string;
  checks: CheckResult[];
}

export interface SettingsGroup {
  kind: SettingsKind;
  title: string;
  description: string;
  fields: SettingsField[];
  configured: boolean;
  updated_at: string | null;
  last_test: TestResult | null;
  required_for_audit: boolean;
}

export interface SettingsView {
  kinds: SettingsGroup[];
  ready: boolean;
  missing: SettingsKind[];
}

export interface ApiKey {
  id: string;
  name: string;
  prefix: string;
  created_at: string;
  last_used_at: string | null;
}

export interface CreatedApiKey {
  token: string;
  key: ApiKey;
  note: string;
}

export interface AuditStartResponse {
  run_id: string;
  status: "running" | "completed" | "failed";
  stats?: AuditStats;
}

export interface AuditRequest {
  tenant?: string;
  documents?: { tenant_id: string; document_id: string }[];
  probe?: boolean;
}

/** One line of GET /api/connections: the live health of a connected system, as measured by the server. */
export interface ConnectionStatus {
  name: string;
  kind: string; // ledger | s3 | postgres | qdrant
  ok: boolean;
  detail: string;
  latency_ms: number | null;
  info: Record<string, unknown>;
}

export type BlastScenario =
  | { type: "open_issues" }
  | { type: "config_change"; target: Record<string, string | number> }
  | { type: "ingestion_failure"; since: string; until?: string };

export interface PlanRequest {
  issue_ids?: string[];
  min_severity?: Severity;
  tenant?: string;
  types?: string[];
}

// ---- tenant isolation ---------------------------------------------------------------------------------------
export type IsolationOverallStatus = "clean" | "attention" | "leak" | "not_applicable" | "limited";
export type IsolationTenantStatus = "leak" | "attention" | "clean" | "single_tenant";
export type IsolationCheckStatus = "pass" | "warn" | "fail" | "na";

export interface IsolationOverall {
  status: IsolationOverallStatus;
  /** A plain sentence written by the server. Shown as is. */
  summary: string;
  tenants: number;
  points_checked: number;
  /** Documents indexed under a tenant they do not belong to. */
  leaking_documents: number;
  /** Of those, how many were searched live as the wrong tenant (absent in a summary stored by an older version). */
  leaks_tested_by_search?: number;
  /** Of the searched ones, how many a live search returned. */
  leaks_confirmed_reachable: number;
  permission_mismatch_documents: number;
  permissions_recorded: boolean;
  tenant_label_pct: number | null;
  /** null when the index does not record permissions at all. */
  permission_label_pct: number | null;
}

export interface IsolationCheck {
  name: string;
  status: IsolationCheckStatus;
  detail: string;
}

export interface IsolationTenant {
  tenant_id: string;
  status: IsolationTenantStatus;
  documents: number;
  points: number;
  tenant_label_pct: number | null;
  permission_label_pct: number | null;
  /** Documents that belong to another tenant but are indexed under this one. */
  foreign_documents: number;
  permission_mismatch_documents: number;
}

export interface IsolationFinding {
  issue_id: string;
  type: IssueType;
  severity: Severity;
  tenant_id: string;
  document_id: string;
  title: string;
  status: IssueStatus;
}

/** GET /api/isolation once a full audit has finished. */
export interface IsolationAvailable {
  available: true;
  audit: { run_id: string; finished_at: string | null; kind: "full" };
  overall: IsolationOverall;
  /** Worst first, at most 200. */
  tenants: IsolationTenant[];
  tenants_total: number;
  /** Always five. */
  checks: IsolationCheck[];
  /** The issues that are open right now (not the ones the last full audit saw). */
  findings: IsolationFinding[];
  findings_total: number;
  findings_live: boolean;
  /** True when the open issues no longer match the counts of the last full audit (a scoped audit, an ignore or a repair since). */
  findings_changed_since_audit: boolean;
}

/** GET /api/isolation before any full audit has finished. */
export interface IsolationUnavailable {
  available: false;
  note: string;
}

export type IsolationView = IsolationAvailable | IsolationUnavailable;

/** POST /api/isolation/drill. Both fields or neither (neither: the server picks a healthy indexed document). */
export interface DrillRequest {
  tenant?: string;
  document_id?: string;
}

export interface DrillFinding {
  type: IssueType;
  severity: Severity;
  tenant_id: string;
  document_id: string;
  title: string;
  detail: string;
}

/** A read-only fire drill: nothing is written, saved or sent. */
export interface DrillResult {
  drill: true;
  document: { tenant_id: string; document_id: string; points: number };
  simulated: string;
  caught: boolean;
  findings: DrillFinding[];
  /** The message an audit would post to the alert webhook. `text` has Slack-style markup (*bold*, `code`, bullets). */
  would_alert: { severity: Severity; sent: boolean; text: string; note: string } | null;
  nothing_changed: string;
}
