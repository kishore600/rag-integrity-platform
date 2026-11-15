import {
  ArrowRight,
  BellRing,
  Cloud,
  Coins,
  Copy,
  Database,
  Eye,
  FileX,
  Gauge,
  GitBranch,
  History,
  KeyRound,
  Layers,
  Lock,
  Mail,
  Network,
  ScanSearch,
  ShieldCheck,
  Trash2,
  Webhook,
  Wrench,
  type LucideIcon,
} from "lucide-react";
import { Link } from "react-router-dom";
import { MEDIA } from "@/lib/help-media";
import { ISSUE_TYPES, issueLabel, issueSources } from "@/lib/issue-meta";
import type { IssueType } from "@/types/api";
import { AUDIT_MAILTO, CONTACT_EMAIL, CONTACT_MAILTO } from "./contact";
import { Container, CtaGhost, CtaGhostHref, CtaPrimary, SectionHeading } from "./ui";

// ---- the problem ---------------------------------------------------------------------------------------
const PROBLEMS: { icon: LucideIcon; title: string; text: string }[] = [
  { icon: FileX, title: "Documents that were never embedded", text: "The file sits in storage, but nothing about it is searchable." },
  { icon: History, title: "Updated documents with old vectors", text: "The source changed. The index keeps serving the previous version with full confidence." },
  { icon: Trash2, title: "Deleted documents that stay searchable", text: "Withdrawn or deleted content can still be returned to your users." },
  { icon: Layers, title: "Half-indexed documents", text: "Only some chunks made it in, so answers are quietly incomplete." },
  { icon: Copy, title: "Duplicates and empty vectors", text: "Retries double-count chunks. Zero vectors can never be retrieved." },
  { icon: GitBranch, title: "Drift nobody planned", text: "The embedding model, the chunking or the permissions changed. Old documents did not." },
];

export function Problem() {
  return (
    <section id="problem" aria-labelledby="problem-title" className="scroll-mt-16 bg-white py-20 sm:py-24">
      <Container>
        <SectionHeading id="problem-title" eyebrow="The problem" title="Your pipeline says success. Your users get the wrong answer.">
          A RAG system can fail silently while every background job reports success. The app keeps running, and nobody finds out until an answer is wrong.
        </SectionHeading>
        <ul className="mt-12 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {PROBLEMS.map((p) => (
            <li key={p.title} className="rounded-card border border-line bg-app p-6">
              <span className="flex h-10 w-10 items-center justify-center rounded-control bg-critical-bg text-critical">
                <p.icon className="h-5 w-5" aria-hidden />
              </span>
              <h3 className="mt-4 text-section text-ink">{p.title}</h3>
              <p className="mt-1.5 text-body text-ink-2">{p.text}</p>
            </li>
          ))}
        </ul>
      </Container>
    </section>
  );
}

// ---- how it works --------------------------------------------------------------------------------------
const STEPS: { icon: LucideIcon; title: string; text: string }[] = [
  { icon: Database, title: "Connect, read-only", text: "Point RAGGuard at your S3 bucket and your vector index, in Qdrant or pgvector. Add the manifest table your pipeline writes to, if you have one, for extra checks. It only ever lists, reads and queries." },
  { icon: ScanSearch, title: "Reconcile", text: "Every document is compared across the systems you connected, chunk by chunk. Retrieval probes check whether bad content can actually be returned to a user." },
  { icon: Wrench, title: "Repair and verify", text: "Plans go to your own worker as signed requests. RAGGuard then checks the real index again. Old vectors are removed only after you approve." },
];

export function HowItWorks() {
  return (
    <section id="how" aria-labelledby="how-title" className="scroll-mt-16 border-y border-line bg-app py-20 sm:py-24">
      <Container>
        <SectionHeading id="how-title" eyebrow="How it works" title="Your documents and your index, one version of the truth" align="center">
          Your documents and your index should agree, and so should your manifest if you keep one. RAGGuard checks that they do, continuously.
        </SectionHeading>
        <ol className="relative mt-14 grid gap-6 md:grid-cols-3">
          <div className="pointer-events-none absolute left-[16%] right-[16%] top-7 hidden border-t border-dashed border-line-strong md:block" aria-hidden />
          {STEPS.map((s, i) => (
            <li key={s.title} className="relative rounded-card border border-line bg-white p-6 shadow-card">
              <div className="flex items-center gap-3">
                <span className="relative flex h-14 w-14 items-center justify-center rounded-full bg-brand text-white shadow-[0_8px_20px_rgba(79,70,229,0.3)]">
                  <s.icon className="h-6 w-6" aria-hidden />
                  <span className="absolute -right-1 -top-1 flex h-6 w-6 items-center justify-center rounded-full border-2 border-white bg-ink text-support font-bold text-white">{i + 1}</span>
                </span>
              </div>
              <h3 className="mt-5 text-section text-ink">{s.title}</h3>
              <p className="mt-2 text-body text-ink-2">{s.text}</p>
            </li>
          ))}
        </ol>
        <Walkthrough />
      </Container>
    </section>
  );
}

/** The narrated walkthrough from the user guide. preload="none": the home page only fetches the video when someone presses play. */
function Walkthrough() {
  return (
    <figure className="mx-auto mt-16 max-w-3xl">
      <h3 className="text-center text-section text-ink">See it working</h3>
      <video
        controls
        preload="none"
        poster={MEDIA.poster}
        className="mt-5 aspect-video w-full rounded-card border border-line bg-night shadow-card"
        aria-label="RAGGuard walkthrough: the Documents page and the Isolation page"
      >
        <source src={MEDIA.mp4Cdn} type="video/mp4" />
        <source src={MEDIA.mp4Static} type="video/mp4" />
        <track kind="captions" src={MEDIA.captions} srcLang="en" label="English" />
        Your browser cannot play this video. <a href={MEDIA.mp4Cdn}>Download it</a>.
      </video>
      <figcaption className="mt-3 text-center text-support text-ink-2">
        A six-minute walkthrough with narration and captions: the Documents page and the Isolation page, on demo data.{" "}
        <Link to="/help" className="font-medium text-brand underline underline-offset-4 hover:text-brand-hover">
          More in the user guide
        </Link>
        .
      </figcaption>
    </figure>
  );
}

// ---- what it finds ------------------------------------------------------------------------------------
// Typed as a full Record: adding an issue type to the product fails the build until it is described here.
const BLURB: Record<IssueType, string> = {
  missing_embedding: "The document is in storage, but nothing about it is searchable.",
  partial_index: "Only some chunks were indexed, so answers are quietly incomplete.",
  stale_embedding: "The source changed, but the index still serves the old version.",
  superseded_active: "Old-generation vectors still answer queries next to the new ones.",
  orphan_vector: "A deleted document is still searchable.",
  duplicate_chunk: "The same chunk was indexed more than once.",
  metadata_inconsistent: "Source, manifest and payloads disagree on counts, versions or permissions.",
  pipeline_drift: "Vectors were built with a different parser, chunker or embedding model.",
  empty_embedding: "Points with a missing or all-zero vector can never be retrieved.",
  tenant_mismatch: "Vectors tagged with the wrong tenant can leak one customer's content to another.",
  manifest_orphan: "The manifest lists a document that exists nowhere else.",
};

export function Detects() {
  return (
    <section id="detects" aria-labelledby="detects-title" className="scroll-mt-16 bg-white py-20 sm:py-24">
      <Container>
        <SectionHeading id="detects-title" eyebrow="What it finds" title={`${ISSUE_TYPES.length} kinds of silent failure, each with evidence`}>
          Every finding says what is wrong, why it matters, which systems are involved and what to do about it.
        </SectionHeading>
        <ul className="mt-12 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {ISSUE_TYPES.map((t) => (
            <li key={t} className="flex flex-col rounded-card border border-line bg-white p-5 transition-colors hover:border-brand/40 hover:bg-brand-light/30">
              <h3 className="text-card text-ink">{issueLabel(t)}</h3>
              <p className="mt-1.5 flex-1 text-body text-ink-2">{BLURB[t]}</p>
              <p className="mt-3 flex flex-wrap gap-1.5">
                {issueSources(t).map((s) => (
                  <span key={s} className="rounded-full bg-surface px-2 py-0.5 text-support text-ink-2">{s}</span>
                ))}
              </p>
            </li>
          ))}
        </ul>
      </Container>
    </section>
  );
}

// ---- what you get -------------------------------------------------------------------------------------
const FEATURES: { icon: LucideIcon; title: string; text: string }[] = [
  { icon: Gauge, title: "A health score you can trust", text: "The share of documents whose index matches the latest source exactly, tracked after every audit." },
  { icon: Eye, title: "Evidence, not guesses", text: "Each finding shows expected versus actual, the values it read, and whether the bad content can really be retrieved." },
  { icon: Coins, title: "Know the cost before you fix", text: "Estimated re-embedding work and cost, compared with rebuilding everything, before you commit to a repair." },
  { icon: Network, title: "Blast radius", text: "Which documents, tenants and queries a pipeline change or an ingestion failure would touch." },
  { icon: Webhook, title: "Safe, verified repairs", text: "Signed requests to your own worker, independent verification, and your approval before any vector is removed." },
  { icon: BellRing, title: "Alerts and automation", text: "Slack-compatible webhook alerts, and API keys to run audits from CI or a scheduler." },
];

export function Features() {
  return (
    <section aria-labelledby="features-title" className="border-y border-line bg-app py-20 sm:py-24">
      <Container>
        <SectionHeading id="features-title" eyebrow="What you get" title="Everything you need to act on it" align="center">
          From the first audit to a verified fix, in one place.
        </SectionHeading>
        <ul className="mt-12 grid gap-x-8 gap-y-10 sm:grid-cols-2 lg:grid-cols-3">
          {FEATURES.map((f) => (
            <li key={f.title} className="flex gap-4">
              <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-control bg-brand-light text-brand">
                <f.icon className="h-5 w-5" aria-hidden />
              </span>
              <div>
                <h3 className="text-section text-ink">{f.title}</h3>
                <p className="mt-1 text-body text-ink-2">{f.text}</p>
              </div>
            </li>
          ))}
        </ul>
      </Container>
    </section>
  );
}

// ---- security -----------------------------------------------------------------------------------------
const SAFE: { icon: LucideIcon; title: string; text: string }[] = [
  { icon: Eye, title: "Read-only by design", text: "RAGGuard lists, reads and queries. It never writes to your S3 bucket, your manifest or your index." },
  { icon: Lock, title: "Credentials stay secret", text: "Encrypted before they are stored, used only to read your systems, and never shown again after you save them." },
  { icon: ShieldCheck, title: "Workspaces are isolated", text: "Every query is scoped to your workspace, so one account can never see another's data." },
  { icon: Network, title: "Private networks blocked", text: "The hosted service only connects to public addresses, so it cannot be pointed at internal services." },
  { icon: Webhook, title: "Signed repairs, approved removals", text: "Repair requests are signed with HMAC-SHA256, and vectors are removed only after you approve." },
  { icon: KeyRound, title: "Hardened sessions", text: "HttpOnly cookies, rate-limited sign-in, scoped API keys and a strict content security policy." },
];

export function Security() {
  return (
    <section id="security" aria-labelledby="security-title" className="relative scroll-mt-16 overflow-hidden bg-night py-20 sm:py-24">
      <div className="pointer-events-none absolute inset-0 bg-dots opacity-50 [mask-image:radial-gradient(ellipse_at_center,black_20%,transparent_75%)]" aria-hidden />
      <Container className="relative">
        <SectionHeading id="security-title" eyebrow="Security" tone="dark" title="Safe to point at production">
          You are giving a verifier access to the systems behind your product. It is built to ask for as little as it can.
        </SectionHeading>
        <ul className="mt-12 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {SAFE.map((s) => (
            <li key={s.title} className="rounded-card border border-white/10 bg-white/[0.04] p-6">
              <span className="flex h-10 w-10 items-center justify-center rounded-control bg-indigo-400/15 text-indigo-300">
                <s.icon className="h-5 w-5" aria-hidden />
              </span>
              <h3 className="mt-4 text-section text-white">{s.title}</h3>
              <p className="mt-1.5 text-body text-slate-300">{s.text}</p>
            </li>
          ))}
        </ul>
      </Container>
    </section>
  );
}

// ---- works with ---------------------------------------------------------------------------------------
const STACK: { icon: LucideIcon; role: string; name: string; text: string }[] = [
  { icon: Cloud, role: "Source documents", name: "Amazon S3", text: "And S3-compatible stores such as MinIO, Cloudflare R2 and Supabase Storage." },
  { icon: Layers, role: "Vector index", name: "Qdrant or pgvector", text: "Qdrant, self-hosted or Cloud. Or a pgvector table in any PostgreSQL: Supabase, Neon or AWS RDS, including LangChain and LlamaIndex tables. Your own field and column names." },
  { icon: Database, role: "Processing manifest (optional)", name: "PostgreSQL", text: "Not needed to start. If your pipeline records what it indexed, connect that table, with your own column names, for extra checks." },
];

export function Stack() {
  return (
    <section aria-labelledby="stack-title" className="bg-white py-20 sm:py-24">
      <Container>
        <SectionHeading id="stack-title" eyebrow="Works with" title="The tools you already run" align="center">
          No agents to install and no pipeline to change. Two connections are enough to start: your documents and your index.
        </SectionHeading>
        <ul className="mt-12 grid gap-4 md:grid-cols-3">
          {STACK.map((s) => (
            <li key={s.name} className="rounded-card border border-line bg-white p-6 shadow-card">
              <span className="flex h-12 w-12 items-center justify-center rounded-control bg-night text-indigo-300">
                <s.icon className="h-6 w-6" aria-hidden />
              </span>
              <p className="mt-4 text-support font-medium uppercase tracking-wide text-ink-2">{s.role}</p>
              <h3 className="text-section text-ink">{s.name}</h3>
              <p className="mt-1.5 text-body text-ink-2">{s.text}</p>
            </li>
          ))}
        </ul>
      </Container>
    </section>
  );
}

// ---- FAQ ----------------------------------------------------------------------------------------------
const FAQS: { q: string; a: string }[] = [
  { q: "Does RAGGuard change my data?", a: "No. It only lists, reads and queries your S3 bucket, your vector index and, if you connect one, your manifest table. Fixes are carried out by your own worker, which RAGGuard asks with a signed request. RAGGuard then checks the real index again." },
  { q: "What do I need to connect?", a: "Two things: an S3 bucket with your source documents, and your vector index, either a Qdrant collection or a pgvector table in PostgreSQL. A manifest table, where your ingestion pipeline records what it indexed, is optional and adds extra checks. The Data Sources page tests each connection and tells you exactly what to change." },
  { q: "How does it know what my index should contain?", a: "It compares the content hash of each file in your source with the hash stored on its vectors. If you connect a manifest, it also compares the chunk counts your pipeline recorded with what is actually indexed. It can also run a search to check whether bad content can really be returned." },
  { q: "How much does it cost?", a: "Nothing while RAGGuard is in beta. Paid plans will come later." },
  { q: "What is a free audit?", a: `Email us at ${CONTACT_EMAIL} and we will set a time. Together we connect RAGGuard to your systems, read-only, run your first audit and go through what it found. You keep the results.` },
  { q: "Can I run audits from CI or on a schedule?", a: "Yes. Create an API key and call the audit endpoint from GitHub Actions, cron or any scheduler. A key can run audits and read results, but it cannot read your settings or create other keys." },
  { q: "How are my credentials protected?", a: "They are encrypted before they are stored, used only from the server to read your systems, and never shown again once saved. The hosted service refuses private and localhost addresses." },
];

export function Faq() {
  return (
    <section id="faq" aria-labelledby="faq-title" className="scroll-mt-16 border-t border-line bg-app py-20 sm:py-24">
      <Container className="grid gap-12 lg:grid-cols-[0.8fr_1.2fr]">
        <SectionHeading id="faq-title" eyebrow="FAQ" title="Questions, answered">
          The usual worries, answered plainly.
        </SectionHeading>
        <div className="divide-y divide-line rounded-card border border-line bg-white">
          {FAQS.map((f) => (
            <details key={f.q} className="group px-6 py-5 [&_summary::-webkit-details-marker]:hidden">
              <summary className="flex cursor-pointer list-none items-center justify-between gap-4 text-card text-ink">
                {f.q}
                <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-surface text-ink-2 transition-transform group-open:rotate-45" aria-hidden>
                  +
                </span>
              </summary>
              <p className="mt-3 text-body leading-6 text-ink-2">{f.a}</p>
            </details>
          ))}
        </div>
      </Container>
    </section>
  );
}

// ---- final call to action -----------------------------------------------------------------------------
export function FinalCta({ canRegister }: { canRegister: boolean }) {
  return (
    <section aria-labelledby="cta-title" className="relative overflow-hidden bg-night py-20 sm:py-24">
      <div className="pointer-events-none absolute left-1/2 top-0 h-[360px] w-[720px] -translate-x-1/2 rounded-full bg-brand/30 blur-[120px]" aria-hidden />
      <Container className="relative text-center">
        <h2 id="cta-title" className="mx-auto max-w-2xl text-[30px] font-bold leading-tight tracking-tight text-white sm:text-[38px]">
          See what your index is really serving.
        </h2>
        <p className="mx-auto mt-4 max-w-xl text-[16px] leading-7 text-slate-300">
          Connect your documents and your index, and run your first audit in minutes. Free during beta.
        </p>
        <div className="mt-8 flex flex-wrap items-center justify-center gap-3">
          {canRegister ? (
            <CtaPrimary to="/signup">
              Create your workspace <ArrowRight className="h-4 w-4" aria-hidden />
            </CtaPrimary>
          ) : null}
          <CtaGhostHref href={AUDIT_MAILTO}>
            <Mail className="h-4 w-4" aria-hidden /> Book a free audit
          </CtaGhostHref>
          {canRegister ? null : <CtaGhost to="/login">Sign in</CtaGhost>}
        </div>
        <p className="mt-6 text-support text-slate-400">
          Questions first? <a href="#faq" className="underline underline-offset-4 hover:text-white">Read the FAQ</a> or email{" "}
          <a href={CONTACT_MAILTO} className="underline underline-offset-4 hover:text-white">{CONTACT_EMAIL}</a>.
        </p>
      </Container>
    </section>
  );
}
