import { FileWarning, KeyRound, Layers, ScanSearch, Tag, Users } from "lucide-react";
import { KpiCard } from "@/components/shared/page";
import { formatNumber, formatPercent } from "@/lib/format";
import type { IsolationOverall } from "@/types/api";
import { plural } from "./meta";

const GRID = "grid gap-4 sm:grid-cols-2 xl:grid-cols-3";

/** A value that is words, not a number: smaller and muted so it does not shout like a count would. */
const words = (text: string) => <span className="text-section text-ink-2">{text}</span>;

/**
 * What the reachability number means. A leak only counts as confirmed when a live search returned it, and not every leak is
 * searched (searches can be off, or the audit's limit on searches can be reached), so "0 confirmed" can mean "unknown".
 * `tested` is undefined for a summary stored by an older version.
 */
function reachabilityHint(leaks: number, tested: number | undefined, confirmed: number): string {
  if (leaks === 0) return "Nothing to confirm";
  if (tested === undefined) return confirmed > 0 ? "returned by a live search" : "Run a full audit to refresh this";
  if (tested === 0) {
    return leaks === 1 ? "Reachability is unknown: the wrong-tenant document was not searched" : `Reachability is unknown: none of the ${formatNumber(leaks)} wrong-tenant documents were searched`;
  }
  return `Searched ${formatNumber(tested)} of ${formatNumber(leaks)} wrong-tenant ${plural(leaks, "document")}`;
}

export function IsolationKpis({ o }: { o: IsolationOverall }) {
  const tested = o.leaks_tested_by_search;
  const limited = o.status === "limited";
  const single = o.status === "not_applicable";
  const unchecked = limited || single;
  const leaks = o.leaking_documents;
  const permissionsRecorded = o.permissions_recorded && o.permission_label_pct !== null;
  const tenantPct = o.tenant_label_pct;
  const permPct = o.permission_label_pct;

  return (
    <div className={GRID}>
      <KpiCard label="Tenants" icon={Users} tone="brand" value={formatNumber(o.tenants)} hint="found in the last full audit" />
      <KpiCard
        label="Vectors checked"
        icon={Layers}
        tone="brand"
        value={formatNumber(o.points_checked)}
        hint={limited ? "only those of documents found in the source" : "read from your index"}
      />
      <KpiCard
        label="Documents under the wrong tenant"
        icon={FileWarning}
        tone={unchecked ? "neutral" : leaks > 0 ? "critical" : "success"}
        value={limited ? words("Not checked") : single ? words("Not applicable") : formatNumber(leaks)}
        hint={limited ? "Needs a full read of the index" : single ? "Only one tenant exists" : leaks > 0 ? "Their content can reach the wrong customer" : "None found"}
      />
      <KpiCard
        label="Confirmed reachable by a search"
        icon={ScanSearch}
        tone={unchecked ? "neutral" : o.leaks_confirmed_reachable > 0 ? "critical" : leaks > 0 && tested !== leaks ? "warning" : "success"}
        value={limited ? words("Not checked") : single ? words("Not applicable") : formatNumber(o.leaks_confirmed_reachable)}
        hint={unchecked ? (limited ? "Needs a full read of the index" : "Only one tenant exists") : reachabilityHint(leaks, tested, o.leaks_confirmed_reachable)}
      />
      <KpiCard
        label="Tenant labels"
        icon={Tag}
        tone={tenantPct === null ? "neutral" : tenantPct >= 100 ? "success" : "warning"}
        value={formatPercent(tenantPct)}
        hint={tenantPct === 0 ? "The payload has no tenant field, so every vector counts as the default tenant" : "of vectors carry a tenant label"}
      />
      <KpiCard
        label="Permission labels"
        icon={KeyRound}
        tone={!permissionsRecorded ? "neutral" : (permPct ?? 0) >= 100 && o.permission_mismatch_documents === 0 ? "success" : "warning"}
        value={permissionsRecorded ? formatPercent(permPct) : words("Not recorded")}
        hint={
          permissionsRecorded ? (
            <>
              of vectors carry a permission label
              {o.permission_mismatch_documents > 0 ? (
                <span className="mt-0.5 block font-medium text-warning">
                  {formatNumber(o.permission_mismatch_documents)} {plural(o.permission_mismatch_documents, "document")} differ from the manifest
                </span>
              ) : null}
            </>
          ) : (
            "Your index does not record permissions, so there is nothing to check"
          )
        }
      />
    </div>
  );
}

export function IsolationKpisSkeleton() {
  return (
    <div className={GRID} aria-hidden>
      <KpiCard loading label="Tenants" icon={Users} value="" hint=" " />
      <KpiCard loading label="Vectors checked" icon={Layers} value="" hint=" " />
      <KpiCard loading label="Documents under the wrong tenant" icon={FileWarning} value="" hint=" " />
      <KpiCard loading label="Confirmed reachable by a search" icon={ScanSearch} value="" hint=" " />
      <KpiCard loading label="Tenant labels" icon={Tag} value="" hint=" " />
      <KpiCard loading label="Permission labels" icon={KeyRound} value="" hint=" " />
    </div>
  );
}
