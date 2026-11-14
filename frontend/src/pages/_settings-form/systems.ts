/**
 * The systems RAGGuard compares, with their saved settings (app mode) and their live health, in one place,
 * so Data Sources and Integrations always agree about what is connected. The source and the vector index are needed; the manifest is optional,
 * and the vector index is Qdrant or pgvector (a PostgreSQL table), whichever the workspace chose.
 */
import { Cloud, Database, Layers, type LucideIcon } from "lucide-react";
import { useConnections, useSession, useSettings } from "@/hooks/queries";
import type { ConnectionStatus, SettingsGroup, SettingsKind } from "@/types/api";
import type { SystemState } from "./parts";

export type SystemKind = "s3" | "manifest" | "qdrant" | "pgvector";
export type IndexType = "qdrant" | "pgvector";

export const SYSTEM_DEFS: { kind: SystemKind; connection: string; eyebrow: string; name: string; icon: LucideIcon; blurb: string; optional?: boolean }[] = [
  { kind: "s3", connection: "s3", eyebrow: "Document source", name: "Amazon S3", icon: Cloud, blurb: "The documents that should be searchable. RAGGuard lists them and reads their metadata." },
  {
    kind: "manifest",
    connection: "postgres",
    eyebrow: "Manifest (optional)",
    name: "PostgreSQL",
    icon: Database,
    blurb: "Optional. The table where your pipeline records what it processed. Without it RAGGuard compares your files with the index directly; with it, it can also check what the pipeline claimed.",
    optional: true,
  },
  { kind: "qdrant", connection: "qdrant", eyebrow: "Vector index", name: "Qdrant", icon: Layers, blurb: "The vector store that answers searches. RAGGuard reads what is actually in it." },
  { kind: "pgvector", connection: "pgvector", eyebrow: "Vector index", name: "pgvector (PostgreSQL)", icon: Layers, blurb: "A PostgreSQL table with a vector column. RAGGuard reads the rows that are actually in it." },
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
  /** An optional system that is not connected is fine: it is not a missing step. */
  optional: boolean;
  state: SystemState;
}

export const SYSTEM_KINDS: SettingsKind[] = ["s3", "manifest", "qdrant", "pgvector", "index"];

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
  // which vector store: the workspace's choice in app mode, otherwise the one the server reports a connection for
  const indexType: IndexType = appMode ? (settings.data?.index_type ?? "qdrant") : health?.some((c) => c.kind === "pgvector") ? "pgvector" : "qdrant";
  const indexGroup = groups?.find((g) => g.kind === "index");

  const systems: SystemStatus[] = SYSTEM_DEFS.filter((d) => d.kind !== (indexType === "pgvector" ? "qdrant" : "pgvector")).map((d) => {
    const group = groups?.find((g) => g.kind === d.kind);
    const connection = health?.find((c) => c.kind === d.connection);
    const configured = appMode ? !!group?.configured : !!connection;
    const optional = !!d.optional;
    let state: SystemState;
    if (!configured) state = optional ? "optional" : appMode || health ? "not_connected" : connections.isPending ? "checking" : "unknown";
    else if (connection) state = connection.ok ? "connected" : "error";
    else if (connections.isPending || connections.isFetching) state = "checking";
    else state = "unknown";
    return { kind: d.kind, eyebrow: d.eyebrow, name: d.name, icon: d.icon, blurb: d.blurb, group, connection, configured, optional, state };
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
    indexType,
    indexGroup,
    ledger,
    refresh,
    fetching: settings.isFetching || connections.isFetching,
  };
}
