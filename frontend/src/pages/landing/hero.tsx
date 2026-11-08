import { ArrowRight, Lock } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Container, CtaGhost, CtaPrimary } from "./ui";

type NodeKind = "ok" | "missing" | "stale" | "orphan" | "gone";
const COLS = [104, 280, 456];
const ROWS = [118, 178, 238, 298, 358];
const PLAN: { cells: [NodeKind, NodeKind, NodeKind] }[] = [
  { cells: ["ok", "ok", "ok"] },
  { cells: ["ok", "ok", "missing"] },
  { cells: ["ok", "ok", "ok"] },
  { cells: ["ok", "ok", "stale"] },
  { cells: ["gone", "gone", "orphan"] },
];

const STYLE: Record<NodeKind, { fill: string; stroke: string; dash?: string; label?: string; labelColor?: string }> = {
  ok: { fill: "rgba(99,102,241,0.14)", stroke: "rgba(129,140,248,0.6)" },
  missing: { fill: "rgba(248,113,113,0.06)", stroke: "#F87171", dash: "4 4", label: "no vectors", labelColor: "#FCA5A5" },
  stale: { fill: "rgba(251,191,36,0.10)", stroke: "#FBBF24", label: "old version", labelColor: "#FCD34D" },
  orphan: { fill: "rgba(248,113,113,0.12)", stroke: "#F87171", label: "still searchable", labelColor: "#FCA5A5" },
  gone: { fill: "none", stroke: "rgba(148,163,184,0.45)", dash: "4 4", label: "deleted", labelColor: "#94A3B8" },
};

function DocNode({ cx, cy, kind }: { cx: number; cy: number; kind: NodeKind }) {
  const s = STYLE[kind];
  return (
    <g>
      <rect x={cx - 54} y={cy - 20} width={108} height={40} rx={10} fill={s.fill} stroke={s.stroke} strokeWidth={1.5} strokeDasharray={s.dash} />
      {kind === "ok" || kind === "stale" || kind === "orphan" ? (
        <>
          <rect x={cx - 40} y={cy - 9} width={52} height={4.5} rx={2.25} fill="#fff" fillOpacity={0.55} />
          <rect x={cx - 40} y={cy + 2} width={34} height={4.5} rx={2.25} fill="#fff" fillOpacity={0.28} />
        </>
      ) : null}
      {kind === "ok" ? <circle cx={cx + 38} cy={cy} r={3.4} fill="#34D399" /> : null}
      {s.label ? (
        <text x={cx} y={kind === "missing" || kind === "gone" ? cy + 4 : cy + 34} textAnchor="middle" fontSize={10.5} fontWeight={600} fill={s.labelColor}>
          {s.label}
        </text>
      ) : null}
    </g>
  );
}

/** An illustration (not data): one document traced across the three systems, with the failures RAGGuard reports. */
function ReconcileIllustration() {
  return (
    <svg viewBox="0 0 560 456" className="h-auto w-full" role="img" aria-label="Illustration: documents checked across Amazon S3, the PostgreSQL manifest and the Qdrant index. One document has no vectors, one was indexed from an old version, and one deleted document is still searchable.">
      <defs>
        <linearGradient id="scanline" x1="0" y1="0" x2="1" y2="0">
          <stop offset="0" stopColor="#818CF8" stopOpacity="0" />
          <stop offset="0.5" stopColor="#A5B4FC" stopOpacity="0.95" />
          <stop offset="1" stopColor="#818CF8" stopOpacity="0" />
        </linearGradient>
        <linearGradient id="scanglow" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#6366F1" stopOpacity="0" />
          <stop offset="1" stopColor="#6366F1" stopOpacity="0.22" />
        </linearGradient>
      </defs>
      <rect x="0.75" y="0.75" width="558.5" height="454.5" rx="20" fill="#0F172A" stroke="rgba(255,255,255,0.09)" strokeWidth="1.5" />

      {/* the three rails */}
      {COLS.map((cx) => (
        <line key={cx} x1={cx} y1={84} x2={cx} y2={384} stroke="rgba(255,255,255,0.07)" strokeWidth={1} />
      ))}
      {[
        ["SOURCE", "Amazon S3"],
        ["MANIFEST", "PostgreSQL"],
        ["INDEX", "Qdrant"],
      ].map(([t, sub], i) => (
        <g key={t}>
          <text x={COLS[i]} y={46} textAnchor="middle" fontSize={11} fontWeight={700} letterSpacing="1.6" fill="#E2E8F0">
            {t}
          </text>
          <text x={COLS[i]} y={63} textAnchor="middle" fontSize={10.5} fill="#94A3B8">
            {sub}
          </text>
        </g>
      ))}

      {/* connectors, then nodes */}
      {PLAN.map((row, r) => (
        <g key={r}>
          {[0, 1].map((c) => {
            const a = row.cells[c];
            const b = row.cells[c + 1];
            const bad = a === "gone" || b === "missing" || b === "orphan" || b === "gone";
            const warn = b === "stale";
            return (
              <line
                key={c}
                x1={COLS[c] + 54}
                y1={ROWS[r]}
                x2={COLS[c + 1] - 54}
                y2={ROWS[r]}
                stroke={bad ? (a === "gone" ? "rgba(148,163,184,0.35)" : "#F87171") : warn ? "#FBBF24" : "rgba(129,140,248,0.7)"}
                strokeWidth={1.6}
                strokeDasharray={bad ? "4 4" : undefined}
              />
            );
          })}
        </g>
      ))}
      {PLAN.map((row, r) => row.cells.map((k, c) => <DocNode key={`${r}-${c}`} cx={COLS[c]} cy={ROWS[r]} kind={k} />))}

      {/* the scan */}
      <g className="hero-scan" style={{ transformBox: "fill-box" }}>
        <rect x={24} y={60} width={512} height={44} fill="url(#scanglow)" />
        <rect x={24} y={103} width={512} height={2} fill="url(#scanline)" />
      </g>

    </svg>
  );
}

export function Hero({ canRegister }: { canRegister: boolean }) {
  return (
    <section aria-labelledby="hero-title" className="relative overflow-hidden bg-night">
      <div className="pointer-events-none absolute inset-0 bg-dots opacity-70 [mask-image:radial-gradient(ellipse_at_top,black_30%,transparent_75%)]" aria-hidden />
      <div className="pointer-events-none absolute -left-40 top-[-120px] h-[460px] w-[460px] rounded-full bg-brand/30 blur-[120px]" aria-hidden />
      <div className="pointer-events-none absolute -right-32 top-24 h-[380px] w-[380px] rounded-full bg-violet-600/20 blur-[120px]" aria-hidden />

      <Container className="relative grid items-center gap-14 py-16 sm:py-20 lg:grid-cols-[1.02fr_0.98fr] lg:gap-10 lg:py-28">
        <div>
          <p className="inline-flex items-center gap-2 rounded-full border border-white/10 bg-white/5 px-3 py-1 text-support font-medium text-indigo-200">
            <span className="h-1.5 w-1.5 rounded-full bg-emerald-400" aria-hidden /> Independent verification for RAG
          </p>
          <h1 id="hero-title" className="mt-6 text-[40px] font-bold leading-[1.05] tracking-tight text-white sm:text-[52px] lg:text-[60px]">
            Know when your RAG index is wrong,{" "}
            <span className="bg-gradient-to-r from-indigo-300 via-indigo-200 to-violet-300 bg-clip-text text-transparent">before your users do.</span>
          </h1>
          <p className="mt-6 max-w-xl text-[17px] leading-8 text-slate-300">
            RAGGuard compares your source documents, your processing manifest and your vector index, then shows exactly what drifted, how serious it is and how to fix it safely.
          </p>
          <div className="mt-9 flex flex-wrap items-center gap-3">
            {canRegister ? (
              <CtaPrimary to="/signup">
                Create your workspace <ArrowRight className="h-4 w-4" aria-hidden />
              </CtaPrimary>
            ) : null}
            <CtaGhost to="/login">Sign in</CtaGhost>
          </div>
          <p className="mt-6 flex items-center gap-2 text-support text-slate-400">
            <Lock className="h-3.5 w-3.5" aria-hidden /> Read-only access to your systems. Credentials are encrypted and never shown again.
          </p>
        </div>

        <div className="relative lg:pl-4">
          <div className="absolute -inset-4 rounded-[28px] bg-gradient-to-br from-brand/25 via-transparent to-violet-500/10 blur-2xl" aria-hidden />
          <div className="relative">
            <ReconcileIllustration />
            <figure className="relative mx-auto -mt-9 w-[calc(100%-32px)] rounded-card border border-white/10 bg-white p-4 shadow-pop sm:ml-auto sm:mr-6 sm:w-[330px]">
              <figcaption className="flex items-center justify-between gap-2">
                <Badge tone="critical" dot>Critical</Badge>
                <span className="text-support text-ink-3">Example finding</span>
              </figcaption>
              <p className="mt-2 text-card text-ink">Document has no embeddings in the index</p>
              <p className="mt-1 text-support text-ink-2">The pipeline reported success, but nothing about this document is searchable.</p>
              <div className="mt-3 grid grid-cols-2 gap-2 text-support">
                <div className="rounded-control border border-success/20 bg-success-bg p-2">
                  <p className="text-ink-2">Expected</p>
                  <p className="font-medium text-ink">All chunks indexed</p>
                </div>
                <div className="rounded-control border border-critical/20 bg-critical-bg p-2">
                  <p className="text-ink-2">Actual</p>
                  <p className="font-medium text-ink">0 vectors found</p>
                </div>
              </div>
            </figure>
          </div>
        </div>
      </Container>
    </section>
  );
}
