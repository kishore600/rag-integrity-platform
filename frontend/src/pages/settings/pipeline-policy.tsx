import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { KeyValue } from "@/components/shared/page";
import { EmptyState, Skeleton } from "@/components/shared/states";
import { useOverview } from "@/hooks/queries";
import type { SettingsKind, SettingsView } from "@/types/api";
import { EnvNote, humanize, QueryGate, SettingsForm } from "../_settings-form";
import type { UseQueryResult } from "@tanstack/react-query";

/** The pipeline the server expects (single-user mode): read from the server, shown as it was measured. */
function ServerPipeline() {
  const overview = useOverview(true);
  return (
    <Card>
      <CardHeader title="Expected pipeline" description="The settings your documents should have been processed with." />
      <CardBody className="space-y-4">
        <EnvNote>Set the RAGI_TARGET_* variables on the server to change what is expected.</EnvNote>
        <QueryGate query={overview} compact skeleton={<Skeleton className="h-24" />}>
          {(o) => {
            const entries = Object.entries(o.target_fingerprint ?? {});
            return entries.length > 0 ? (
              <KeyValue items={entries.map(([k, v]) => ({ label: humanize(k), value: String(v) }))} />
            ) : (
              <EmptyState compact title="No expected pipeline is set" description="Without one, RAGGuard cannot report vectors built with a different parser, chunking or embedding setup." />
            );
          }}
        </QueryGate>
      </CardBody>
    </Card>
  );
}

function GroupCard({ kind, settings, title, description, intro }: { kind: SettingsKind; settings: UseQueryResult<SettingsView, unknown>; title: string; description: string; intro: string }) {
  return (
    <QueryGate query={settings} skeleton={<Skeleton className="h-96" />}>
      {(view) => {
        const group = view.kinds.find((k) => k.kind === kind);
        if (!group) return <EmptyState title="This group of settings is not available" />;
        return (
          <Card>
            <CardHeader title={title} description={description} />
            <CardBody className="space-y-5">
              <p className="max-w-3xl text-body text-ink-2">{intro}</p>
              <SettingsForm group={group} testLabel={null} />
            </CardBody>
          </Card>
        );
      }}
    </QueryGate>
  );
}

export function PipelineTab({ appMode, settings }: { appMode: boolean; settings: UseQueryResult<SettingsView, unknown> }) {
  if (!appMode) return <ServerPipeline />;
  return (
    <GroupCard
      kind="pipeline"
      settings={settings}
      title="Expected pipeline"
      description="How your documents should currently be processed."
      intro="This is the pipeline you expect. RAGGuard compares it with how each document was actually processed, and reports vectors built with a different parser, chunking or embedding setup as pipeline drift. Leave a field empty to use the default."
    />
  );
}

export function PolicyTab({ appMode, settings }: { appMode: boolean; settings: UseQueryResult<SettingsView, unknown> }) {
  if (!appMode) {
    return (
      <Card>
        <CardHeader title="Audit policy" description="How audits judge documents and how repair costs are estimated." />
        <CardBody>
          <EnvNote>The grace period, default tenant, required payload fields and embedding price come from the server&apos;s configuration, not from this page.</EnvNote>
        </CardBody>
      </Card>
    );
  }
  return (
    <GroupCard
      kind="policy"
      settings={settings}
      title="Audit policy"
      description="How audits judge documents and how repair costs are estimated."
      intro="The grace period decides how long a document that was just changed or is still being processed counts as pending instead of broken. The default tenant is assumed when a vector or manifest row names none. The required payload fields are what every vector must carry. The embedding price and tokens per chunk are used only for cost estimates. Leave a field empty to use the default."
    />
  );
}
