import { FlaskConical, Info, Settings2, type LucideIcon } from "lucide-react";
import type { ReactNode } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { LinkButton } from "@/components/shared/link-button";
import { Mono } from "@/components/shared/page";
import { links } from "@/lib/links";
import { SOURCE_ONLY_LABEL } from "./meta";

export const DRILL_LABEL = "Run isolation drill";

/** The drill button. One component so every place that offers the drill looks and reads the same. */
export function DrillButton({ onClick, variant = "primary", loading, className }: { onClick: () => void; variant?: "primary" | "secondary"; loading?: boolean; className?: string }) {
  return (
    <Button variant={variant} onClick={onClick} loading={loading} className={className}>
      {loading ? null : <FlaskConical className="h-4 w-4" aria-hidden />}
      {DRILL_LABEL}
    </Button>
  );
}

function ExplainCard({ icon: Icon, title, children, actions }: { icon: LucideIcon; title: string; children: ReactNode; actions: ReactNode }) {
  return (
    <Card className="p-5">
      <div className="flex items-start gap-3">
        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-control bg-info-bg text-info">
          <Icon className="h-[18px] w-[18px]" aria-hidden />
        </span>
        <div className="min-w-0 flex-1">
          <h2 className="text-section text-ink">{title}</h2>
          <div className="mt-2 max-w-3xl space-y-2 text-body text-ink-2">{children}</div>
          <div className="mt-4 flex flex-wrap items-center gap-2">{actions}</div>
        </div>
      </div>
    </Card>
  );
}

const drillSentence = "It takes one of your own documents, pretends in memory that its vectors belong to another tenant, and shows what RAGGuard would report. Nothing is changed.";

/** `limited`: the audit read only documents found in the source, so wrong-tenant vectors were never seen. */
export function LimitedCard({ appMode, onDrill }: { appMode: boolean; onDrill: () => void }) {
  return (
    <ExplainCard
      icon={Info}
      title="Why this check is limited"
      actions={
        <>
          <DrillButton onClick={onDrill} />
          <LinkButton variant="secondary" to={links.settings("policy")}>
            <Settings2 className="h-4 w-4" aria-hidden /> Open audit policy settings
          </LinkButton>
        </>
      }
    >
      <p>
        This audit only read documents it found in your source (S3). A vector indexed under the wrong tenant belongs to a document the audit never reads, so it cannot be seen. RAGGuard says so here instead of telling you everything is clean.
      </p>
      {appMode ? (
        <p>
          To check for real, turn off <span className="font-medium text-ink">&ldquo;{SOURCE_ONLY_LABEL}&rdquo;</span> in Settings, under Policy, then run a full audit.
        </p>
      ) : (
        <p>
          To check for real, set <Mono>RAGI_SOURCE_DOCUMENTS_ONLY</Mono> to false on the server (it is the &ldquo;{SOURCE_ONLY_LABEL}&rdquo; setting), then run a full audit.
        </p>
      )}
      <p>
        <span className="font-medium text-ink">The drill still works.</span> It is the way to see this feature in action today. {drillSentence}
      </p>
    </ExplainCard>
  );
}

/** `not_applicable`: one tenant only, so there is nothing to keep apart. */
export function SingleTenantCard({ onDrill }: { onDrill: () => void }) {
  return (
    <ExplainCard icon={Info} title="Why there is nothing to compare yet" actions={<DrillButton onClick={onDrill} />}>
      <p>Only one tenant was found, so there is no other customer whose content could reach its answers. Isolation checks apply once your documents belong to several tenants.</p>
      <p>
        <span className="font-medium text-ink">The drill still works.</span> It is the way to see this feature in action with a single tenant. {drillSentence}
      </p>
    </ExplainCard>
  );
}

const POINTS: { lead: string; body: ReactNode }[] = [
  {
    lead: "A leak",
    body: "is a document whose vectors are indexed under a tenant it does not belong to. A search made for that other tenant can return its content.",
  },
  {
    lead: "Confirmed reachable",
    body: "means RAGGuard searched your index as the wrong tenant and the document really came back. It turns a likely leak into a proven one. Not every leak is searched, so 0 can mean unknown: the card says how many were searched.",
  },
  {
    lead: "The label percentages",
    body: (
      <>
        show how many vectors carry a tenant label (<Mono>tenant_id</Mono>) and a permission label. Below 100% means some vectors cannot be kept apart reliably. Permission labels are only checked when your index records them.
      </>
    ),
  },
  {
    lead: "The isolation drill",
    body: "is a practice run on one of your own documents. It pretends in memory that its vectors belong to another tenant, and shows what the audit would raise and the alert it would send. It never writes to your S3, database or index, saves no issue and sends no alert.",
  },
];

export function HowToReadCard() {
  return (
    <Card>
      <CardHeader title="How to read this page" description="The result comes from the latest full audit. A scoped audit does not change it." />
      <CardBody>
        <ul className="max-w-3xl list-disc space-y-2.5 pl-5 text-body text-ink-2 marker:text-ink-3">
          {POINTS.map((p) => (
            <li key={p.lead}>
              <span className="font-medium text-ink">{p.lead}</span> {p.body}
            </li>
          ))}
        </ul>
      </CardBody>
    </Card>
  );
}
