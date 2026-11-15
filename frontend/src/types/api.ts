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

/** An ID problem the audit noticed but could not resolve: it still ran, and its findings are valid (GUIDE.md section 3.4). */
export interface RunWarning {
  code: "duplicate_source_ids" | "duplicate_manifest_ids" | "empty_manifest_ids";
  severity: "warning";
  title: string;
  detail: string;
  fix: string;
  count: number;
  examples?: { tenant_id: string; document_id: string; copies: number; found_in: string[] }[];
}

/** How complete and how reliable the scan of the vector index was (GUIDE.md 3.12). Absent on runs recorded before it existed. */
export interface ScanBlock {
  status: "completed" | "partial" | "failed" | "in_progress";
  complete: boolean;
  /** true while the result is not final: a partial audit reports only the documents it finished. */
  provisional: boolean;
  mode: "sliced" | "single_pass";
  points_scanned: number;
  estimated_total: number | null;
  percent: number | null;
  pages: number;
  retries: number;
  recovered_errors: number;
  unrecoverable_errors: number;
  rate_limited: number;
  waited_seconds: number;
  slices_total: number;
  slices_done: number;
  documents_done: number | null;
  documents_total: number | null;
  checkpoint: [string, string] | null;
  resumed_from: string | null;
  stopped_because: string | null;
}

export interface AuditStats {
  /** Absent on runs recorded before ID warnings existed: treat as none. */
  warnings?: RunWarning[];
  scan?: ScanBlock;
  /** Whether a manifest took part in this audit, and which checks were left out when it did not. */
  manifest?: { connected: boolean; checks_not_run?: string[] };
  deletion_check?: { documents_checked: number; with_remaining_vectors: number; verified_gone: number };
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

/** Where the audit in progress stands (running, or queued for a worker). `state` says what to do about it, if anything. */
export interface AuditProgress {
  run_id: string | null;
  status: "queued" | "running";
  state: "working" | "queued" | "waiting_for_worker" | "silent";
  message: string;
  done_documents: number | null;
  total_documents: number | null;
  percent: number | null;
  last_worker: string | null;
}

export interface AuditRun {
  id: string;
  workspace_id: string;
  kind: "full" | "scoped" | "verify";
  trigger: string;
  scope: { tenant?: string; documents?: number };
  status: "queued" | "running" | "completed" | "partial" | "failed";
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

/** An interrupted full audit that can be continued (GUIDE.md 3.12). */
export interface ResumableAudit {
  run_id: string;
  finished_at: string | null;
  documents_done: number | null;
  documents_total: number | null;
  percent: number | null;
  stopped_because: string | null;
}

export interface Overview {
  mode: string;
  resumable_audit?: ResumableAudit | null;
  /** False when no manifest is connected (it is optional). */
  manifest_connected?: boolean;
  index_type?: "qdrant" | "pgvector";
  demo: boolean;
  documents: { total: number; by_status: Record<string, number>; health_score: number | null; tenants: TenantHealth[] };
  issues: { open: number; by_severity: Record<Severity, number>; by_type: Record<string, number>; resolved: number; ignored: number };
  latest_run: AuditRun | null;
  latest_full_run: AuditRun | null;
  trend: { at: string | null; health_score: number | null; findings: number | null; documents: number | null }[];
  audit_running: boolean;
  audit_progress: AuditProgress | null;
  audit_queue: boolean;
  query_log_size: number;
  target_fingerprint: Record<string, string | number> | null;
  scheduler_interval_minutes: number;
  cleanup_policy: string;
  repair_webhook_configured: boolean;
  email_configured: boolean;
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
  manifest_connected?: boolean;
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
export type SettingsKind = "s3" | "manifest" | "qdrant" | "index" | "pgvector" | "pipeline" | "repair" | "alerts" | "email" | "policy";
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
  /** Where this workspace's vectors are: Qdrant (the default) or pgvector. */
  index_type?: "qdrant" | "pgvector";
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

/** One step a notification offers. A `link` opens a page of the app; a `post` calls one of two known endpoints (see hooks/use-notification-actions.ts). */
export interface NotificationAction {
  id: string;
  label: string;
  kind: "link" | "post";
  target: string;
  primary?: boolean;
  body?: Record<string, unknown>;
}

/** What an audit told the workspace when it finished, and what to do about it. */
export interface AppNotification {
  id: string;
  kind: "audit_completed" | "audit_partial" | "audit_failed";
  tone: "success" | "info" | "warning" | "critical";
  title: string;
  body: string;
  details: string[];
  run_id: string | null;
  actions: NotificationAction[];
  created_at: string;
  read_at: string | null;
  /** The id of the action that was taken from this notification, if any. */
  done_action: string | null;
  emailed_at: string | null;
}

export interface NotificationList {
  items: AppNotification[];
  unread: number;
}

/** The answer of the Send test email button (POST /api/alerts/test-email). `reason` says in words why nothing was sent. */
export interface TestEmailResult {
  ok: boolean;
  sent: number;
  to: string[];
  reason?: string;
  rate_limited?: boolean;
}

/** The answer of the deletion check (GUIDE.md 3.13): only the numbers the notification button reports. */
export interface DeletionCheckResult {
  summary: {
    documents_checked: number;
    verified_deleted: number;
    deletion_mismatch: number;
    manifest_not_updated: number;
    not_deleted: number;
    vectors_remaining: number;
    retrievable: number;
  };
  note?: string;
}

export interface AuditStartResponse {
  run_id: string;
  status: "queued" | "running" | "completed" | "partial" | "failed";
  stats?: AuditStats;
}

export interface AuditRequest {
  tenant?: string;
  documents?: { tenant_id: string; document_id: string }[];
  probe?: boolean;
  /** Continue the last audit that stopped part-way, from its checkpoint (a full audit only: leave out tenant and documents). */
  resume?: boolean;
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

/** What repairing everything that matches would do, before anything is created or sent. */
export interface BulkPreview {
  documents: number;
  issues: number;
  by_severity: Record<string, number>;
  summary: WorkloadSummary;
  to_reprocess: number;
  cleanup_only: number;
  webhook_configured: boolean;
  email_configured: boolean;
}

export interface BulkRepairRequest {
  min_severity?: Severity;
  tenant?: string;
  types?: string[];
  send?: boolean;
  email_to?: string;
  note?: string;
}

/** Each step reports for itself: the plan can exist and be sent while the email could not be. */
export interface BulkRepairResponse {
  plan: RepairPlan;
  sent: boolean;
  emailed: string[] | null;
  problems: { step: "send" | "email"; message: string }[];
}

export interface EmailPlanRequest {
  to: string;
  note?: string;
  attach_payload?: boolean;
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

// ---- setup and coverage check (POST /api/setup-check, GUIDE.md section 3.10) -----------------------------------
export type SetupStatus = "ready" | "needs_attention" | "not_ready";
export type SetupCheckStatus = "pass" | "warn" | "fail" | "na";

export interface SetupCheckItem {
  id: string;
  name: string;
  status: SetupCheckStatus;
  /** Plain words with the real numbers in them. */
  detail: string;
  fix?: string;
  /** Real IDs or file names, shown in monospace. */
  examples?: string[];
  hint?: string;
  numbers?: { matched: number; of: number };
}

export interface CoverageLink {
  matched: number;
  of: number;
  percent: number;
}

/** The result is always an HTTP 200, even when a connection is missing (then `checks` holds one `connections` check and most else is empty). */
export interface SetupCheckResult {
  status: SetupStatus;
  headline: string;
  /** False when no manifest is connected: only S3 and the index were compared. */
  manifest_connected?: boolean;
  /** What the vector store is called in the messages ("Qdrant" or "pgvector"). */
  index_label?: string;
  checks: SetupCheckItem[];
  coverage: { source_to_manifest?: CoverageLink | null; manifest_to_source?: CoverageLink | null; source_to_index?: CoverageLink | null };
  counts: {
    source_files?: number | null;
    source_documents?: number | null;
    source_files_skipped?: number | null;
    manifest_rows?: number | null;
    manifest_documents?: number | null;
    index_points_approx?: number | null;
    index_points_sampled?: number | null;
    manifest_connected?: boolean;
  };
  ids_at_a_glance: { source?: string[]; manifest?: string[]; index?: string[] };
  id_types_in_index: Partial<Record<"integer" | "digits" | "text" | "decimal" | "other", number>>;
  /** Notes about anything that was cut short. */
  limits: string[];
  next_steps: string[];
  generated_at?: string;
  duration_seconds?: number | null;
}
