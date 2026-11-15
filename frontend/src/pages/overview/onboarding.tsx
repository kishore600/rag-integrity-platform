import { Check, Circle } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { ErrorState, Skeleton } from "@/components/shared/states";
import { LinkButton } from "@/components/shared/link-button";
import { useSettings } from "@/hooks/queries";
import type { SettingsKind } from "@/types/api";

interface Step {
  kind: SettingsKind;
  title: string;
  system: string;
  description: string;
  optional?: boolean;
}

/** The source and the vector index are needed; the manifest is optional. The index is whichever of Qdrant and pgvector the workspace chose. */
function stepsFor(indexType: string | undefined): Step[] {
  return [
    { kind: "s3", title: "Document source", system: "Amazon S3", description: "The documents your users should be able to search." },
    indexType === "pgvector"
      ? { kind: "pgvector", title: "Vector index", system: "pgvector", description: "The PostgreSQL table your application actually searches." }
      : { kind: "qdrant", title: "Vector index", system: "Qdrant", description: "The store your application actually searches." },
    { kind: "manifest", title: "Manifest", system: "PostgreSQL", description: "Optional. The table where your pipeline records what it indexed. It adds checks, but audits work without it.", optional: true },
  ];
}

/** Shown instead of data while a workspace has not connected its source and its vector index. Only mounted in app mode, so /api/settings exists. */
export function OnboardingCard() {
  const q = useSettings();

  if (q.isError) {
    return (
      <Card>
        <ErrorState error={q.error} onRetry={() => void q.refetch()} />
      </Card>
    );
  }

  const STEPS = stepsFor(q.data?.index_type);
  const required = STEPS.filter((s) => !s.optional);
  const configured = (kind: SettingsKind): boolean | undefined => (q.data ? q.data.kinds.find((k) => k.kind === kind)?.configured ?? false : undefined);
  const done = required.filter((s) => configured(s.kind)).length;
  const next = required.find((s) => configured(s.kind) === false)?.kind;

  return (
    <Card className="mx-auto max-w-3xl">
      <div className="border-b border-line px-6 py-5">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="text-section text-ink">Connect your data</h2>
          {q.data ? <span className="text-support tabular-nums text-ink-2">{done} of {required.length} connected</span> : <Skeleton className="h-4 w-24" />}
        </div>
        <p className="mt-1 text-body text-ink-2">RAGGuard compares your documents with your vector index. Connect both, then run your first audit. A manifest is optional.</p>
      </div>
      <ol className="divide-y divide-line">
        {STEPS.map((s, i) => {
          const isDone = configured(s.kind);
          return (
            <li key={s.kind} className="flex flex-wrap items-center gap-4 px-6 py-4">
              <span
                className={isDone ? "flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-success-bg text-success" : "flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-surface text-ink-2"}
                aria-hidden
              >
                {isDone ? <Check className="h-4 w-4" /> : <Circle className="h-4 w-4" />}
              </span>
              <div className="min-w-0 flex-1 basis-56">
                <p className="text-body font-medium text-ink">
                  {i + 1}. {s.title} <span className="font-normal text-ink-2">({s.system}{s.optional ? ", optional" : ""})</span>
                </p>
                <p className="text-support text-ink-2">{s.description}</p>
              </div>
              <div className="flex items-center gap-3">
                {isDone === undefined ? <Skeleton className="h-5 w-14" /> : <Badge tone={isDone ? "success" : "neutral"}>{isDone ? "Done" : s.optional ? "Optional" : "To do"}</Badge>}
                <LinkButton to="/data-sources" variant={s.kind === next ? "primary" : "secondary"} size="sm">
                  {isDone ? "Review" : "Set up"}
                </LinkButton>
              </div>
            </li>
          );
        })}
      </ol>
    </Card>
  );
}
