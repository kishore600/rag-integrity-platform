/**
 * The three systems RAGGuard compares, with their saved settings (app mode) and their live health, in one place,
 * so Data Sources and Integrations always agree about what is connected.
 */
import { Cloud, Database, Layers, type LucideIcon } from "lucide-react";
import { useConnections, useSession, useSettings } from "@/hooks/queries";
import type { ConnectionStatus, SettingsGroup, SettingsKind } from "@/types/api";
import type { SystemState } from "./parts";

export type SystemKind = "s3" | "manifest" | "qdrant";

export const SYSTEM_DEFS: { kind: SystemKind; connection: string; eyebrow: string; name: string; icon: LucideIcon; blurb: string }[] = [
  { kind: "s3", connection: "s3", eyebrow: "Document source", name: "Amazon S3", icon: Cloud, blurb: "The documents that should be searchable. RAGGuard lists them and reads their metadata." },
  { kind: "manifest", connection: "postgres", eyebrow: "Manifest", name: "PostgreSQL", icon: Database, blurb: "The table where your pipeline records what it processed for each document." },
  { kind: "qdrant", connection: "qdrant", eyebrow: "Vector index", name: "Qdrant", icon: Layers, blurb: "The vector store that answers searches. RAGGuard reads what is actually in it." },
];

export interface SystemStatus {
  kind: SystemKind;
  eyebrow: string;
  name: string;
  icon: LucideIcon;
  blurb: string;
  group: SettingsGroup | undefined;
  connection: ConnectionStatus | undefined;
  configured: boolean;
  state: SystemState;
}

export const SYSTEM_KINDS: SettingsKind[] = ["s3", "manifest", "qdrant"];

export function useSystems() {
  const session = useSession().data;
  const appMode = !!session?.app;
  // /api/settings only exists in app mode; single-user servers take their connections from environment variables
  const settings = useSettings(appMode);
  const groups = settings.data?.kinds;
  const anyConfigured = appMode ? !!groups?.some((g) => SYSTEM_KINDS.includes(g.kind) && g.configured) : !!session;
  const connections = useConnections(anyConfigured);

  const health = connections.data;
  const ledger = health?.find((c) => c.kind === "ledger");

  const systems: SystemStatus[] = SYSTEM_DEFS.map((d) => {
    const group = groups?.find((g) => g.kind === d.kind);
    const connection = health?.find((c) => c.kind === d.connection);
    const configured = appMode ? !!group?.configured : !!connection;
    let state: SystemState;
    if (!configured) state = appMode || health ? "not_connected" : connections.isPending ? "checking" : "unknown";
    else if (connection) state = connection.ok ? "connected" : "error";
    else if (connections.isPending || connections.isFetching) state = "checking";
    else state = "unknown";
    return { kind: d.kind, eyebrow: d.eyebrow, name: d.name, icon: d.icon, blurb: d.blurb, group, connection, configured, state };
  });

  async function refresh() {
    await Promise.all([appMode ? settings.refetch() : Promise.resolve(), anyConfigured ? connections.refetch() : Promise.resolve()]);
  }

  return {
    session,
    appMode,
    settings,
    connections,
    systems,
    ledger,
    refresh,
    fetching: settings.isFetching || connections.isFetching,
  };
}
