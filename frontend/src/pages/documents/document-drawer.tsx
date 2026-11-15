import type { ColumnDef } from "@tanstack/react-table";
import { AlertTriangle, CheckCircle2, ChevronRight, RefreshCw, ScanSearch, ShieldCheck, XCircle, Wrench } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { Badge, type Tone } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Drawer } from "@/components/ui/overlays";
import { Tabs, TabsContent, TabsList, TabsTrigger, Tip } from "@/components/ui/menus";
import { DataTable } from "@/components/shared/data-table";
import { KeyValue, Mono, Section } from "@/components/shared/page";
import { EmptyState, ErrorState, Skeleton } from "@/components/shared/states";
import { DocStateBadge, IssueStatusBadge, SeverityBadge } from "@/components/shared/status";
import { useCreatePlan, useDocument, useManifestConnected } from "@/hooks/queries";
import { useRunAudit } from "@/hooks/use-run-audit";
import { ApiError, errorMessage } from "@/lib/api";
import { cn } from "@/lib/cn";
import { formatBytes, formatDateTime, formatNumber, shortHash, timeAgo } from "@/lib/format";
import { issueLabel } from "@/lib/issue-meta";
import { links } from "@/lib/links";
import type { DocumentDetail, DocumentRow, LiveSnapshot } from "@/types/api";

const cap = (s: string): string => s.charAt(0).toUpperCase() + s.slice(1).replace(/_/g, " ");

const STATUS_TONE: Record<string, Tone> = { healthy: "success", degraded: "warning", broken: "critical", pending: "info", orphaned: "neutral" };
const CLASS_TONE: Record<string, Tone> = { fresh: "success", stale: "warning", outdated: "warning", orphan: "critical", unknown: "neutral" };
const CLASS_HELP: Record<string, string> = {
  fresh: "matches the current source and pipeline",
  stale: "built from an older version of the document",
  outdated: "current content, built with an older pipeline setup",
  orphan: "the document no longer exists at the source",
  unknown: "the index does not say which version it is",
};

/** A hash or version id, shortened, with the full value on hover. */
function Hash({ value, n = 14 }: { value: string | null | undefined; n?: number }) {
  if (!value) return <span className="text-ink-3">—</span>;
  return <span title={value}><Mono>{shortHash(value, n)}</Mono></span>;
}

function versionsDiffer(d: Pick<DocumentRow, "source_version" | "indexed_version">): boolean {
  return !!d.source_version && !!d.indexed_version && d.source_version !== d.indexed_version;
}

// ---- overview -----------------------------------------------------------------------------------------------
function Presence({ label, system, present, na }: { label: string; system: string; present: boolean; na?: boolean }) {
  if (na) {
    return (
      <div className="rounded-control border border-line bg-surface p-3">
        <span className="text-card text-ink">{label}</span>
        <p className="mt-1 text-support text-ink-2">{system}</p>
        <p className="mt-1 text-support font-medium text-ink-2">Not connected</p>
      </div>
    );
  }
  return (
    <div className={cn("rounded-control border p-3", present ? "border-success/30 bg-success-bg" : "border-critical/30 bg-critical-bg")}>
      <div className="flex items-center gap-1.5">
        {present ? <CheckCircle2 className="h-4 w-4 shrink-0 text-success" aria-hidden /> : <XCircle className="h-4 w-4 shrink-0 text-critical" aria-hidden />}
        <span className="text-card text-ink">{label}</span>
      </div>
      <p className="mt-1 text-support text-ink-2">{system}</p>
      <p className={cn("mt-1 text-support font-medium", present ? "text-success" : "text-critical")}>{present ? "Present" : "Missing"}</p>
    </div>
  );
}

function OverviewTab({ detail }: { detail: DocumentDetail }) {
  const d = detail.document;
  const manifestConnected = useManifestConnected();
  if (!d) {
    return (
      <div className="px-5 py-5">
        <p className="rounded-control bg-surface px-3 py-2.5 text-body text-ink-2">
          RAGGuard has issues recorded for this document but no audit snapshot of it, which usually means it no longer exists in any system. See the Issues tab.
        </p>
      </div>
    );
  }
  const differ = versionsDiffer(d);
  const openIssues = detail.issues.filter((i) => i.status === "open").length;
  const fingerprint = Object.entries(d.fingerprint ?? {});

  return (
    <div className="divide-y divide-line">
      <Section title="Status">
        <div className="flex flex-wrap items-center gap-2">
          <DocStateBadge doc={d} />
          <Badge tone={STATUS_TONE[d.status] ?? "neutral"}>Audit result: {cap(d.status)}</Badge>
          <span className="text-body text-ink-2 tabular-nums">
            {openIssues === 0 ? "No open issues" : `${formatNumber(openIssues)} open issue${openIssues === 1 ? "" : "s"}`}
          </span>
          {d.worst_severity && openIssues > 0 ? <SeverityBadge severity={d.worst_severity} /> : null}
        </div>
      </Section>

      <Section title="Where this document exists" description={manifestConnected ? "RAGGuard compares these three systems." : "RAGGuard compares these two systems. No manifest is connected, and it is optional."}>
        <div className="grid grid-cols-3 gap-3">
          <Presence label="Source" system="Amazon S3" present={!!d.source_present} />
          <Presence label="Manifest" system="PostgreSQL" present={!!d.manifest_present} na={!manifestConnected} />
          <Presence label="Index" system="Vector index" present={!!d.index_present} />
        </div>
      </Section>

      <Section title="Details">
        <KeyValue
          items={[
            { label: "Source URI", value: d.source_uri ? <Mono>{d.source_uri}</Mono> : "—" },
            { label: "Source hash", value: <Hash value={d.source_hash} /> },
            { label: "Source version", value: <Hash value={d.source_version} /> },
            {
              label: "Indexed version",
              value: (
                <span className="inline-flex items-center gap-1.5">
                  <Hash value={d.indexed_version} />
                  {differ ? (
                    <Tip content="Index was built from a different version">
                      <span className="inline-flex" tabIndex={0} aria-label="Index was built from a different version">
                        <AlertTriangle className="h-4 w-4 text-warning" aria-hidden />
                      </span>
                    </Tip>
                  ) : null}
                </span>
              ),
            },
            { label: "Size", value: <span className="tabular-nums">{formatBytes(d.size_bytes)}</span> },
            {
              label: "Chunks (indexed / expected)",
              value: (
                <span className={cn("tabular-nums", d.expected_chunks !== null && d.indexed_chunks !== d.expected_chunks && "text-warning")}>
                  {formatNumber(d.indexed_chunks)} / {d.expected_chunks === null ? "—" : formatNumber(d.expected_chunks)}
                </span>
              ),
            },
            {
              label: "Collections",
              value: d.collections.length ? (
                <span className="flex flex-wrap gap-1.5">
                  {d.collections.map((c) => (
                    <Mono key={c}>{c}</Mono>
                  ))}
                </span>
              ) : (
                "—"
              ),
            },
            { label: "Manifest status", value: d.manifest_status ? cap(d.manifest_status) : manifestConnected ? "No manifest row" : "Not connected" },
            { label: "Manifest updated", value: d.manifest_updated_at ? <span title={formatDateTime(d.manifest_updated_at)}>{formatDateTime(d.manifest_updated_at)}</span> : "—" },
            {
              label: "Last verified",
              value: (
                <span>
                  <span title={formatDateTime(d.last_verified_at)}>{formatDateTime(d.last_verified_at)}</span> <span className="text-ink-2">({timeAgo(d.last_verified_at)})</span>
                  {d.last_run_id ? (
                    <>
                      {" · "}
                      <Link to={links.audit(d.last_run_id)} className="text-brand hover:underline">View audit run</Link>
                    </>
                  ) : null}
                </span>
              ),
            },
          ]}
        />
      </Section>

      <Section title="Pipeline fingerprint" description="How the indexed vectors for this document were produced.">
        {fingerprint.length === 0 ? (
          <p className="text-body text-ink-2">No pipeline details were recorded for this document.</p>
        ) : (
          <KeyValue items={fingerprint.map(([k, v]) => ({ label: cap(k), value: String(v) }))} />
        )}
      </Section>
    </div>
  );
}

// ---- live inspection ------------------------------------------------------------------------------------------
type Chunk = LiveSnapshot["index"]["chunks"][number];

const chunkColumns: ColumnDef<Chunk, any>[] = [ // eslint-disable-line @typescript-eslint/no-explicit-any
  {
    id: "chunk",
    header: "Chunk",
    accessorFn: (r) => r.chunk_id,
    meta: { className: "min-w-[200px]" },
    cell: ({ row }) => <span className="block max-w-[260px] truncate font-mono text-support" title={row.original.chunk_id}>{row.original.chunk_id}</span>,
  },
  { id: "index", header: "Index", accessorFn: (r) => r.chunk_index ?? -1, meta: { className: "w-[80px] text-right tabular-nums" }, cell: ({ row }) => (row.original.chunk_index === null ? "—" : row.original.chunk_index) },
  { id: "class", header: "Class", accessorFn: (r) => r.class, meta: { className: "w-[110px]" }, cell: ({ row }) => <Badge tone={CLASS_TONE[row.original.class] ?? "neutral"}>{cap(row.original.class)}</Badge> },
  {
    id: "copies",
    header: "Copies",
    accessorFn: (r) => r.copies,
    meta: { className: "w-[80px] text-right tabular-nums" },
    cell: ({ row }) => (row.original.copies > 1 ? <span className="font-medium text-warning" title="This chunk is indexed more than once">{row.original.copies}</span> : row.original.copies),
  },
  { id: "collection", header: "Collection", accessorFn: (r) => r.collection, meta: { className: "min-w-[120px]" }, cell: ({ row }) => <span className="block max-w-[180px] truncate text-ink-2" title={row.original.collection}>{row.original.collection}</span> },
];

function LiveSkeleton() {
  return (
    <div className="space-y-4 px-5 py-4" aria-busy aria-label="Reading your source, manifest and index">
      <p className="text-body text-ink-2">Reading Amazon S3, PostgreSQL and Qdrant. This can take a few seconds.</p>
      <Skeleton className="h-24 w-full" />
      <Skeleton className="h-24 w-full" />
      <Skeleton className="h-48 w-full" />
    </div>
  );
}

function LiveView({ live }: { live: LiveSnapshot }) {
  const { source, manifest, index } = live;
  const classes = Object.entries(index.by_class);
  const mixed = index.fingerprints.length > 1;
  return (
    <div className="divide-y divide-line">
      <Section title="Source" description="Amazon S3">
        {source ? (
          <KeyValue
            items={[
              { label: "Source URI", value: <Mono>{source.source_uri}</Mono> },
              { label: "Version", value: <Hash value={source.source_version} /> },
              { label: "Hash", value: <span className="inline-flex flex-wrap items-center gap-1.5"><Hash value={source.source_hash} />{!source.hash_reliable ? <Badge tone="warning">Multipart ETag</Badge> : null}</span> },
              { label: "Size", value: <span className="tabular-nums">{formatBytes(source.size_bytes)}</span> },
              { label: "Last modified", value: source.last_modified ? formatDateTime(source.last_modified) : "—" },
            ]}
          />
        ) : (
          <p className="text-body text-ink-2">Not found in the source. The document does not exist in S3 right now.</p>
        )}
      </Section>

      <Section title="Manifest" description="PostgreSQL">
        {manifest ? (
          <KeyValue
            items={[
              { label: "Processing status", value: manifest.processing_status ? cap(manifest.processing_status) : "—" },
              { label: "Last updated", value: manifest.updated_at ? formatDateTime(manifest.updated_at) : "—" },
              { label: "Source hash", value: <Hash value={manifest.source_hash} /> },
              { label: "Source version", value: <Hash value={manifest.source_version} /> },
              { label: "Indexed version", value: <Hash value={manifest.indexed_version} /> },
              { label: "Chunks expected / indexed", value: <span className="tabular-nums">{manifest.expected_chunk_count === null ? "—" : formatNumber(manifest.expected_chunk_count)} / {manifest.indexed_chunk_count === null ? "—" : formatNumber(manifest.indexed_chunk_count)}</span> },
              ...Object.entries(manifest.fingerprint ?? {}).map(([k, v]) => ({ label: cap(k), value: String(v) })),
            ]}
          />
        ) : (
          <p className="text-body text-ink-2">{live.manifest_connected === false ? "No manifest is connected. It is optional: connect one on the Data Sources page for the checks that need it." : "No manifest row. The pipeline has no record of this document."}</p>
        )}
        {live.expected_chunks.length > 0 ? <p className="mt-3 text-support text-ink-2">The manifest lists <span className="tabular-nums">{formatNumber(live.expected_chunks.length)}</span> expected chunk{live.expected_chunks.length === 1 ? "" : "s"}.</p> : null}
      </Section>

      <Section title="Index" description="Qdrant">
        <div className="flex flex-wrap items-center gap-x-6 gap-y-2">
          <p className="text-body text-ink"><span className="text-section tabular-nums">{formatNumber(index.points)}</span> <span className="text-ink-2">vectors</span></p>
          {index.collections.map((c) => (
            <Mono key={c}>{c}</Mono>
          ))}
        </div>
        {classes.length > 0 ? (
          <>
            <div className="mt-3 flex flex-wrap gap-2" aria-label="Vectors by class">
              {classes.map(([cls, n]) => (
                <Badge key={cls} tone={CLASS_TONE[cls] ?? "neutral"}>{cap(cls)}: <span className="tabular-nums">{formatNumber(n)}</span></Badge>
              ))}
            </div>
            <ul className="mt-3 space-y-0.5 text-support text-ink-2">
              {classes.map(([cls]) => (
                <li key={cls}><span className="font-medium text-ink">{cap(cls)}</span>: {CLASS_HELP[cls] ?? "other"}</li>
              ))}
            </ul>
          </>
        ) : null}
        {mixed ? <p className="mt-3 rounded-control bg-warning-bg px-3 py-2 text-support text-ink">Vectors for this document were built with {index.fingerprints.length} different pipeline setups.</p> : null}
      </Section>

      <Section title={`Chunks (${formatNumber(index.chunks.length)}${index.chunks_truncated ? "+" : ""})`}>
        {index.chunks.length === 0 ? (
          <p className="text-body text-ink-2">No chunks for this document are in the index.</p>
        ) : (
          <div className="-mx-5 border-y border-line">
            <DataTable label="Indexed chunks" data={index.chunks} columns={chunkColumns} pageSize={10} getRowId={(r) => `${r.collection}/${r.chunk_id}/${r.class}`} />
          </div>
        )}
        {index.chunks_truncated ? <p className="mt-3 text-support text-ink-2">The index holds more chunks than are shown here. Only the first 500 are listed.</p> : null}
      </Section>

      <Section title="Findings from this check" description="What an audit would report for this document right now.">
        {live.findings.length === 0 ? (
          <p className="text-body text-ink-2">No integrity problems found.</p>
        ) : (
          <ul className="divide-y divide-line rounded-control border border-line">
            {live.findings.map((f) => (
              <li key={f.id} className="flex flex-wrap items-start gap-x-3 gap-y-1 px-3 py-2.5">
                <SeverityBadge severity={f.severity} />
                <div className="min-w-0 flex-1 basis-full sm:basis-0">
                  <p className="text-body font-medium text-ink">{f.title}</p>
                  <p className="text-support text-ink-2">{issueLabel(f.type)}</p>
                </div>
              </li>
            ))}
          </ul>
        )}
      </Section>
    </div>
  );
}

function ChunksTab({ requested, onInspect, query }: { requested: boolean; onInspect: () => void; query: ReturnType<typeof useDocument> }) {
  if (!requested) {
    return (
      <div className="px-5 py-5">
        <div className="rounded-card border border-dashed border-line-strong bg-app p-5">
          <div className="flex items-start gap-3">
            <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-control bg-brand-light text-brand"><ScanSearch className="h-[18px] w-[18px]" aria-hidden /></span>
            <div className="min-w-0">
              <h3 className="text-card text-ink">Inspect this document live</h3>
              <p className="mt-1 text-body text-ink-2">
                The Overview shows what the last audit saw. Live inspection reads the document from Amazon S3, its row in the manifest and its vectors in Qdrant right now, and lists every chunk in the index. It can take a few seconds.
              </p>
              <Button variant="primary" className="mt-4" onClick={onInspect}>
                <ScanSearch className="h-4 w-4" aria-hidden /> Inspect live
              </Button>
            </div>
          </div>
        </div>
      </div>
    );
  }
  if (query.isPending) return <LiveSkeleton />;
  if (query.isError) return <div role="alert"><ErrorState error={query.error} onRetry={() => void query.refetch()} compact /></div>;
  const live = query.data.live;
  if (!live) return <EmptyState compact title="No live data came back" description="Try inspecting again." action={<Button variant="secondary" onClick={() => void query.refetch()}>Try again</Button>} />;
  return (
    <>
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-line px-5 py-3">
        <p className="flex items-center gap-2 text-support text-ink-2">
          <Badge tone={STATUS_TONE[live.status] ?? "neutral"} dot>{cap(live.status)}</Badge>
          Read just now{query.isFetching ? ", refreshing" : ""}
        </p>
        <Button variant="secondary" size="sm" onClick={() => void query.refetch()} loading={query.isFetching}>
          <RefreshCw className="h-3.5 w-3.5" aria-hidden /> Inspect again
        </Button>
      </div>
      <LiveView live={live} />
    </>
  );
}

// ---- issues ------------------------------------------------------------------------------------------------------
function IssuesTabContent({ detail }: { detail: DocumentDetail }) {
  if (detail.issues.length === 0) return <EmptyState compact icon={ShieldCheck} title="No issues for this document" description="The last audit found nothing wrong with it." />;
  return (
    <ul className="divide-y divide-line">
      {detail.issues.map((i) => (
        <li key={i.id}>
          <Link to={links.issue(i.id)} className="flex items-start gap-3 px-5 py-3 hover:bg-surface-hover">
            <div className="min-w-0 flex-1">
              <p className="truncate text-body font-medium text-ink" title={i.title}>{i.title}</p>
              <p className="mt-0.5 text-support text-ink-2">{issueLabel(i.type)}</p>
              <div className="mt-1.5 flex flex-wrap items-center gap-2">
                <SeverityBadge severity={i.severity} />
                <IssueStatusBadge status={i.status} />
              </div>
            </div>
            <ChevronRight className="mt-1 h-4 w-4 shrink-0 text-ink-3" aria-hidden />
          </Link>
        </li>
      ))}
    </ul>
  );
}

// ---- drawer ------------------------------------------------------------------------------------------------------
export function DocumentDrawer({ tenant, doc, onClose }: { tenant: string; doc: string; onClose: () => void }) {
  const navigate = useNavigate();
  const base = useDocument(tenant, doc, false);
  const [liveRequested, setLiveRequested] = useState(false);
  // The live read only starts when asked for: no tenant, no request.
  const liveQuery = useDocument(liveRequested ? tenant : undefined, doc, true);
  const [tab, setTab] = useState("overview");
  const audit = useRunAudit();
  const createPlan = useCreatePlan();

  const detail = base.data;
  const row = detail?.document ?? null;
  const notFound = base.error instanceof ApiError && base.error.status === 404;
  const openPlannable = (detail?.issues ?? []).filter((i) => i.status === "open" && i.document_id !== "*");
  const name = doc.split("/").filter(Boolean).pop() ?? doc;

  async function makePlan() {
    try {
      const plan = await createPlan.mutateAsync({ issue_ids: openPlannable.map((i) => i.id) });
      toast.success("Repair plan created", { description: "Review it, then trigger the repair." });
      navigate(links.issues({ view: "plans", plan: plan.id }));
    } catch (err) {
      toast.error("Couldn't create the repair plan", { description: errorMessage(err) });
    }
  }

  function inspect() {
    setLiveRequested(true);
    setTab("chunks");
  }

  return (
    <Drawer
      open
      onOpenChange={(o) => {
        if (!o) onClose();
      }}
      width="xl"
      title={notFound ? "Document not found" : <span title={doc}>{name}</span>}
      description={
        notFound ? undefined : (
          <span className="flex flex-wrap items-center gap-2">
            {row ? <DocStateBadge doc={row} /> : null}
            <span className="truncate" title={tenant}>Tenant {tenant}</span>
          </span>
        )
      }
    >
      {base.isPending ? (
        <div className="space-y-4 px-5 py-5" aria-busy aria-label="Loading document">
          <Skeleton className="h-9 w-64" />
          <Skeleton className="h-24 w-full" />
          <Skeleton className="h-40 w-full" />
        </div>
      ) : notFound ? (
        <EmptyState
          title="Document not found"
          description="RAGGuard has no record of this document in this workspace. It may have been removed, or it was never part of an audit."
          action={<Button variant="secondary" onClick={onClose}>Back to documents</Button>}
        />
      ) : base.isError ? (
        <ErrorState error={base.error} onRetry={() => void base.refetch()} compact />
      ) : detail ? (
        <>
          <div className="flex flex-wrap items-center gap-2 border-b border-line px-5 py-3">
            <Button
              variant="secondary"
              onClick={() => audit.run({ documents: [{ tenant_id: tenant, document_id: doc }] })}
              loading={audit.running}
              disabled={!!audit.disabledReason && !audit.running}
              title={audit.disabledReason ?? undefined}
            >
              <RefreshCw className="h-4 w-4" aria-hidden /> Re-audit document
            </Button>
            {openPlannable.length > 0 ? (
              <Button variant="primary" onClick={makePlan} loading={createPlan.isPending}>
                <Wrench className="h-4 w-4" aria-hidden /> Create repair plan
              </Button>
            ) : null}
          </div>
          <Tabs value={tab} onValueChange={setTab}>
            <TabsList className="px-5" aria-label="Document views">
              <TabsTrigger value="overview">Overview</TabsTrigger>
              <TabsTrigger value="chunks">Chunks</TabsTrigger>
              <TabsTrigger value="issues">
                Issues
                <span className="rounded-full bg-surface px-1.5 text-support tabular-nums text-ink-2">{detail.issues.length}</span>
              </TabsTrigger>
            </TabsList>
            <TabsContent value="overview" className="pt-0">
              <OverviewTab detail={detail} />
            </TabsContent>
            <TabsContent value="chunks" className="pt-0">
              <ChunksTab requested={liveRequested} onInspect={inspect} query={liveQuery} />
            </TabsContent>
            <TabsContent value="issues" className="pt-0">
              <IssuesTabContent detail={detail} />
            </TabsContent>
          </Tabs>
        </>
      ) : null}
    </Drawer>
  );
}

