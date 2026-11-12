import { ClipboardCheck, GaugeCircle, RefreshCw, SearchCheck, Trash2, Users, Wrench, type LucideIcon } from "lucide-react";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/menus";
import { SeverityBadge } from "@/components/shared/status";
import { issueLabel } from "@/lib/issue-meta";
import type { IssueType, Severity } from "@/types/api";
import { Container, SectionHeading } from "./ui";

/**
 * The situations RAGGuard catches, in plain words. They are the same thirteen situations the practice lab plants on purpose, one of each
 * (`tests/test_landing_scenarios.py` fails if the two lists drift apart), and every "RAGGuard shows" is a finding the audit really
 * produces. The ratings are the usual ones: the engine sets severity from the evidence it reads.
 */
interface Scenario {
  fault: string; // the lab's name for it; keeps this list in step with the practice lab
  title: string;
  what: string;
  users: string;
  shows: IssueType;
  severity: Severity;
  fix: string;
}

const GROUPS: { id: string; label: string; blurb: string; items: Scenario[] }[] = [
  {
    id: "missing",
    label: "Missing from search",
    blurb: "The document exists, but your users cannot find it, or cannot find all of it.",
    items: [
      { fault: "never_embedded", title: "A document nobody ever processed", what: "The file is in your bucket, but the pipeline never picked it up: no manifest row and nothing in the index.", users: "Nobody can find it, and no error is ever shown.", shows: "missing_embedding", severity: "high", fix: "Re-run it through your pipeline. A repair plan sends it to your worker." },
      { fault: "false_success", title: "The pipeline said success. The index is empty.", what: "The manifest records success and a chunk count, but the index holds nothing for the document.", users: "Dashboards stay green while the document is invisible. This is the most dangerous case.", shows: "missing_embedding", severity: "critical", fix: "Re-index it, then find out why the pipeline reports success before the vectors are written." },
      { fault: "partial", title: "Half indexed: the worker died part way", what: "Only some of the chunks reached the index, while the manifest claims all of them.", users: "Answers about the missing parts are wrong or empty.", shows: "partial_index", severity: "critical", fix: "Re-index only the missing chunks." },
      { fault: "empty_embedding", title: "Vectors that can never match", what: "Some points exist, but their vector is empty or all zeros.", users: "Parts of the document can never be found.", shows: "empty_embedding", severity: "high", fix: "Re-index the document." },
    ],
  },
  {
    id: "outdated",
    label: "Out of date",
    blurb: "The index answers with confidence from a version that is no longer true.",
    items: [
      { fault: "stale", title: "The document changed. The index did not.", what: "The file was updated after it was indexed, so the manifest and the vectors describe the old version.", users: "The chatbot answers from an outdated version.", shows: "stale_embedding", severity: "high", fix: "Re-index so the vectors match the current file." },
      { fault: "superseded", title: "Old and new versions both searchable", what: "The update was indexed correctly, but the previous version's vectors were never removed.", users: "Old and new text both appear in answers.", shows: "superseded_active", severity: "high", fix: "Once the new version is verified, remove the old vectors after you approve it." },
      { fault: "drift", title: "Mixed pipelines in one index", what: "Some documents were built with an older parser, chunking or embedding model than the one you run now.", users: "Search quality is uneven, and old and new vectors cannot be compared.", shows: "pipeline_drift", severity: "high", fix: "Re-index with the current pipeline. RAGGuard shows the estimated cost before you commit." },
    ],
  },
  {
    id: "leftovers",
    label: "Left behind",
    blurb: "Content that should be gone, or that is counted twice.",
    items: [
      { fault: "deleted_with_manifest", title: "Deleted, but still answering", what: "The file was deleted from your bucket, but its vectors and its manifest row are still there.", users: "The chatbot can still quote a document that no longer exists.", shows: "orphan_vector", severity: "critical", fix: "Remove the leftover vectors after you approve, then the manifest row." },
      { fault: "deleted_no_manifest", title: "Deleted, with no record it ever existed", what: "The file and its manifest row are gone, but the vectors are still in the index, and nothing in your records points at them.", users: "Deleted content stays searchable.", shows: "orphan_vector", severity: "critical", fix: "Remove the leftover vectors after you approve." },
      { fault: "duplicate", title: "The same passage, twice", what: "A retried job inserted chunks a second time with new IDs.", users: "The same passage comes back twice and crowds out other results.", shows: "duplicate_chunk", severity: "medium", fix: "Remove the extra copies after you approve." },
    ],
  },
  {
    id: "records",
    label: "Records disagree",
    blurb: "The documents are fine. The records about them are not.",
    items: [
      { fault: "acl_mismatch", title: "Permissions out of sync", what: "The permission hash in the manifest differs from the one stored on the vectors.", users: "People may see a document they should not, or be blocked from one they should see.", shows: "metadata_inconsistent", severity: "high", fix: "Correct the permission metadata. No re-embedding is needed." },
      { fault: "count_mismatch", title: "The counts do not add up", what: "The manifest says more chunks were indexed than the index really holds.", users: "Usually nothing visible, but you cannot trust your own records.", shows: "metadata_inconsistent", severity: "medium", fix: "Correct the manifest, or re-index if chunks are really missing." },
    ],
  },
  {
    id: "customer",
    label: "Wrong customer",
    blurb: "One customer's content under another customer's label. Per-customer results and a read-only drill are on the Isolation page.",
    items: [
      { fault: "tenant_mismatch", title: "Another customer's label", what: "A document's vectors carry a different tenant's label, and the real document then looks missing.", users: "Content can be returned to the wrong customer: a data leak.", shows: "tenant_mismatch", severity: "critical", fix: "Re-index under the right tenant, then remove the wrongly labelled vectors." },
    ],
  },
];

const TOTAL = GROUPS.reduce((n, g) => n + g.items.length, 0);

function ScenarioCard({ s }: { s: Scenario }) {
  const label = "text-support font-semibold uppercase tracking-wide text-ink-2";
  return (
    <li className="flex flex-col rounded-card border border-line bg-white p-6 shadow-card">
      <h3 className="text-section text-ink">{s.title}</h3>
      <p className="mt-2 text-body text-ink-2">{s.what}</p>
      <dl className="mt-5 space-y-4 border-t border-line pt-5 text-body">
        <div>
          <dt className={label}>What your users notice</dt>
          <dd className="mt-1 text-ink">{s.users}</dd>
        </div>
        <div>
          <dt className={label}>What RAGGuard shows</dt>
          <dd className="mt-1.5 flex flex-wrap items-center gap-2 text-ink">
            <SeverityBadge severity={s.severity} />
            <span className="font-medium">{issueLabel(s.shows)}</span>
          </dd>
        </div>
        <div>
          <dt className={label}>How it gets fixed</dt>
          <dd className="mt-1 text-ink">{s.fix}</dd>
        </div>
      </dl>
    </li>
  );
}

export function Scenarios() {
  return (
    <section id="scenarios" aria-labelledby="scenarios-title" className="scroll-mt-16 border-y border-line bg-app py-20 sm:py-24">
      <Container>
        <SectionHeading id="scenarios-title" eyebrow="Scenarios" title={`${TOTAL} real situations RAGGuard catches`}>
          Each one looks fine from the outside: jobs succeed and dashboards stay green. Pick a group to see what your users would notice, what
          RAGGuard shows and how it gets fixed.
        </SectionHeading>
        <Tabs defaultValue={GROUPS[0].id} className="mt-10">
          <TabsList aria-label="Groups of situations">
            {GROUPS.map((g) => (
              <TabsTrigger key={g.id} value={g.id}>
                {g.label}
                <span className="rounded-full bg-surface px-1.5 text-support text-ink-2">{g.items.length}</span>
              </TabsTrigger>
            ))}
          </TabsList>
          {GROUPS.map((g) => (
            <TabsContent key={g.id} value={g.id} className="pt-8">
              <p className="max-w-2xl text-body text-ink-2">{g.blurb}</p>
              <ul className="mt-5 grid gap-4 md:grid-cols-2">
                {g.items.map((s) => (
                  <ScenarioCard key={s.fault} s={s} />
                ))}
              </ul>
            </TabsContent>
          ))}
        </Tabs>
        <p className="mt-8 max-w-3xl text-support text-ink-2">
          The ratings shown are the usual ones. RAGGuard sets severity from the evidence it reads: for example, a gap the pipeline reported as a
          success is rated higher, and a deleted document that a test search can really return is rated critical.
        </p>
      </Container>
    </section>
  );
}

// ---- when to use it -----------------------------------------------------------------------------------
const USES: { icon: LucideIcon; title: string; text: string; who: string }[] = [
  { icon: RefreshCw, title: "After every ingestion run", text: "Run an audit from CI or a scheduler with an API key, and get a Slack-compatible alert when the index has drifted.", who: "Platform and data engineers" },
  { icon: Wrench, title: "Before you change the embedding model or parser", text: "See which documents the change would touch and what re-embedding would cost, then check afterwards that nothing was left on the old version.", who: "AI and platform teams" },
  { icon: Trash2, title: "When content is deleted or withdrawn", text: "Check that a removed document is really gone from search, not only from storage.", who: "Content owners and compliance teams" },
  { icon: Users, title: "When you serve more than one customer", text: "Check that no customer's content carries another customer's label, and see the result for each customer on the Isolation page.", who: "Security and SaaS teams" },
  { icon: SearchCheck, title: "When a user says the answer is wrong", text: "Look up the document, see whether the source, the manifest and the index agree, and inspect the live pieces to find out why.", who: "Support and AI product teams" },
  { icon: ClipboardCheck, title: "When someone asks for proof", text: "Share a health score, the history of every audit and exported results, so you can show what was checked and when.", who: "Product owners and leadership" },
];

export function UseCases() {
  return (
    <section id="use-cases" aria-labelledby="use-cases-title" className="scroll-mt-16 bg-white py-20 sm:py-24">
      <Container>
        <SectionHeading id="use-cases-title" eyebrow="Use cases" title="Where RAGGuard earns its place" align="center">
          Run it once to see where you stand, then keep it running so the next silent failure is caught the day it happens.
        </SectionHeading>
        <ul className="mt-12 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {USES.map((u) => (
            <li key={u.title} className="flex flex-col rounded-card border border-line bg-white p-6 shadow-card">
              <span className="flex h-11 w-11 items-center justify-center rounded-control bg-brand-light text-brand">
                <u.icon className="h-5 w-5" aria-hidden />
              </span>
              <h3 className="mt-4 text-section text-ink">{u.title}</h3>
              <p className="mt-1.5 flex-1 text-body text-ink-2">{u.text}</p>
              <p className="mt-4 flex items-center gap-2 border-t border-line pt-4 text-support text-ink-2">
                <GaugeCircle className="h-3.5 w-3.5 text-brand" aria-hidden />
                <span>
                  <span className="font-semibold text-ink">For</span> {u.who}
                </span>
              </p>
            </li>
          ))}
        </ul>
      </Container>
    </section>
  );
}
