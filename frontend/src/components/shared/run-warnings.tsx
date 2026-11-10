import { ArrowRight, TriangleAlert } from "lucide-react";
import { Link } from "react-router-dom";
import { Badge } from "@/components/ui/badge";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { formatNumber } from "@/lib/format";
import { links } from "@/lib/links";
import type { RunWarning } from "@/types/api";

/**
 * Warnings about document IDs that an audit noticed but could not resolve (two files or two manifest rows with the same ID, rows with
 * no ID). The audit still ran and its findings are valid, so these are amber notices, never errors. Runs recorded before this existed
 * have no `warnings` key: that means none.
 */
export const runWarnings = (stats: { warnings?: RunWarning[] } | undefined | null): RunWarning[] => stats?.warnings ?? [];

const intro = "The audit still ran and its findings are valid, but some document IDs could not be told apart.";

function SetupCheckLink() {
  return (
    <Link to={links.setupCheck()} className="inline-flex items-center gap-1 font-medium text-brand hover:underline">
      Run the setup check <ArrowRight className="h-3.5 w-3.5" aria-hidden />
    </Link>
  );
}

/** The short version for the Overview: one amber notice that names each problem and points to the details. */
export function RunWarningsNotice({ warnings, runId }: { warnings: RunWarning[]; runId: string }) {
  if (warnings.length === 0) return null;
  return (
    <div role="status" className="flex items-start gap-2.5 rounded-card border border-warning/30 bg-warning-bg px-4 py-3">
      <TriangleAlert className="mt-0.5 h-4 w-4 shrink-0 text-warning" aria-hidden />
      <div className="min-w-0 text-body text-ink">
        <p className="font-medium">Some document IDs were ambiguous in the latest full audit</p>
        <p className="mt-0.5 text-ink-2">{intro}</p>
        <ul className="mt-2 list-disc space-y-0.5 pl-5">
          {warnings.map((w) => (
            <li key={w.code}>
              {w.title} <span className="tabular-nums text-ink-2">({formatNumber(w.count)})</span>
            </li>
          ))}
        </ul>
        <p className="mt-2.5 flex flex-wrap items-center gap-x-5 gap-y-1">
          <Link to={links.audit(runId)} className="inline-flex items-center gap-1 font-medium text-brand hover:underline">
            See the details <ArrowRight className="h-3.5 w-3.5" aria-hidden />
          </Link>
          <SetupCheckLink />
        </p>
      </div>
    </div>
  );
}

function Examples({ warning }: { warning: RunWarning }) {
  const rows = warning.examples ?? [];
  if (rows.length === 0) return null;
  return (
    <div className="mt-3 overflow-x-auto rounded-control border border-line bg-workspace">
      <table className="w-full min-w-[32rem] border-collapse text-left text-table">
        <thead>
          <tr className="border-b border-line bg-surface">
            <th className="table-head px-3 py-2 font-medium">Document ID</th>
            <th className="table-head px-3 py-2 font-medium">Tenant</th>
            <th className="table-head px-3 py-2 font-medium">Copies</th>
            <th className="table-head px-3 py-2 font-medium">Where they are</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={`${r.tenant_id}/${r.document_id}`} className="border-b border-line align-top last:border-0">
              <td className="px-3 py-2 font-mono text-support text-ink">{r.document_id}</td>
              <td className="px-3 py-2 text-ink-2">{r.tenant_id}</td>
              <td className="px-3 py-2 tabular-nums text-ink">{formatNumber(r.copies)}</td>
              <td className="px-3 py-2">
                <ul className="space-y-0.5">
                  {r.found_in.map((where) => (
                    <li key={where} className="break-all font-mono text-support text-ink-2">
                      {where}
                    </li>
                  ))}
                </ul>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** The full version for an audit's own page: each warning with what happened, what to do, and example IDs with where their copies are. */
export function RunWarningsSection({ warnings }: { warnings: RunWarning[] }) {
  if (warnings.length === 0) return null;
  return (
    <Card id="id-warnings" className="border-warning/30">
      <CardHeader title="Warnings about document IDs" description={intro} actions={<SetupCheckLink />} />
      <CardBody>
        <ul className="divide-y divide-line">
          {warnings.map((w) => (
            <li key={w.code} className="py-5 first:pt-0 last:pb-0">
              <p className="flex flex-wrap items-center gap-2 text-card text-ink">
                <TriangleAlert className="h-4 w-4 shrink-0 text-warning" aria-hidden />
                {w.title}
                <Badge tone="warning">{formatNumber(w.count)}</Badge>
              </p>
              <p className="mt-1.5 text-body text-ink-2">{w.detail}</p>
              <p className="mt-2 text-body text-ink">
                <span className="font-medium">What to do: </span>
                {w.fix}
              </p>
              <Examples warning={w} />
            </li>
          ))}
        </ul>
      </CardBody>
    </Card>
  );
}
