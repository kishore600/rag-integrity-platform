import { ArrowRight, Compass, Mail } from "lucide-react";
import { useEffect } from "react";
import { Link, useParams } from "react-router-dom";
import { Card } from "@/components/ui/card";
import { LinkButton } from "@/components/shared/link-button";
import { EmptyState } from "@/components/shared/states";
import { GuideMarkdown, type ResolvedHref } from "@/pages/help/markdown";
import { AUDIT_MAILTO } from "@/pages/landing/contact";

/**
 * The how-to guides: one Markdown file per problem in docs/guides, readable on GitHub and here at /guides/<slug>. A file is
 * "NN-<slug>.md"; its first "# " line is the title and its first "> " line the one-sentence summary (the page description).
 */
const sources = import.meta.glob<string>("../../../../docs/guides/*.md", { query: "?raw", import: "default", eager: true });

export interface Guide {
  slug: string;
  file: string;
  title: string;
  summary: string;
  text: string;
}

const stem = (path: string) => path.replace(/^.*\//, "").replace(/\.md$/, "");

function parse(path: string, text: string): Guide {
  const file = stem(path);
  return {
    file,
    slug: file.replace(/^\d+-/, ""),
    title: /^#\s+(.+?)\s*$/m.exec(text)?.[1] ?? file,
    summary: /^>\s+(.+?)\s*$/m.exec(text)?.[1] ?? "",
    text,
  };
}

const entries = Object.entries(sources).sort(([a], [b]) => a.localeCompare(b));
export const GUIDES: Guide[] = entries.filter(([p]) => stem(p) !== "README").map(([p, t]) => parse(p, t));
export const GUIDES_README = parse("README.md", entries.find(([p]) => stem(p) === "README")?.[1] ?? "# Guides");

const bySlug = new Map(GUIDES.map((g) => [g.slug, g]));
const byFile = new Map(GUIDES.map((g) => [g.file, g]));

/** `03-two-versions.md#check` -> /guides/two-versions#check; `README.md` -> /guides; `/signup` stays an app route. */
export function resolveGuideHref(href: string): ResolvedHref {
  if (href.startsWith("#")) return { native: href };
  if (/^(https?:|mailto:)/i.test(href)) return { external: href };
  if (href.startsWith("/")) return { to: href };
  const [path, fragment] = href.split("#");
  const frag = fragment ? `#${fragment}` : "";
  if (path === "README.md") return { to: `/guides${frag}` };
  const g = byFile.get(path.replace(/\.md$/, ""));
  return g ? { to: `/guides/${g.slug}${frag}` } : { unavailable: true };
}

function usePageTitle(title: string) {
  useEffect(() => {
    const previous = document.title;
    document.title = `${title} · RAGGuard`;
    return () => {
      document.title = previous;
    };
  }, [title]);
}

function TryIt() {
  return (
    <Card className="mt-12 max-w-3xl p-6">
      <h2 className="text-section text-ink">Check all of this automatically</h2>
      <p className="mt-1.5 text-body text-ink-2">
        RAGGuard runs every check in these guides against your S3 bucket and your Qdrant or pgvector index, read-only, and shows the evidence and a safe fix for
        each problem. It is free during the beta.
      </p>
      <div className="mt-4 flex flex-wrap gap-3">
        <LinkButton variant="primary" to="/signup">
          Create your workspace <ArrowRight className="h-4 w-4" aria-hidden />
        </LinkButton>
        <a href={AUDIT_MAILTO} className="inline-flex h-9 items-center gap-2 rounded-control border border-line bg-workspace px-3.5 text-body font-medium text-ink hover:bg-surface">
          <Mail className="h-4 w-4" aria-hidden /> Book a free audit
        </a>
      </div>
    </Card>
  );
}

/** `/guides`: the contents page (docs/guides/README.md). */
export function GuidesIndex() {
  usePageTitle(GUIDES_README.title);
  return (
    <div className="mx-auto max-w-3xl py-4">
      <GuideMarkdown text={GUIDES_README.text} resolveHref={resolveGuideHref} />
      <TryIt />
    </div>
  );
}

/** `/guides/<slug>`: one guide, then the others. */
export function GuidePage() {
  const { slug = "" } = useParams();
  const guide = bySlug.get(slug);
  usePageTitle(guide?.title ?? "Guide not found");
  if (!guide) {
    return (
      <EmptyState
        icon={Compass}
        title="That guide doesn't exist"
        description="The address doesn't match one of the guides."
        action={
          <LinkButton variant="primary" to="/guides">
            All guides
          </LinkButton>
        }
      />
    );
  }
  const others = GUIDES.filter((g) => g.slug !== slug);
  return (
    <div className="mx-auto max-w-3xl py-4">
      <GuideMarkdown text={guide.text} resolveHref={resolveGuideHref} />
      <TryIt />
      <nav aria-label="Other guides" className="mt-12 max-w-3xl border-t border-line pt-6">
        <h2 className="text-section text-ink">More guides</h2>
        <ul className="mt-3 space-y-2">
          {others.map((g) => (
            <li key={g.slug}>
              <Link to={`/guides/${g.slug}`} className="text-body font-medium text-brand hover:text-brand-hover hover:underline">
                {g.title}
              </Link>
            </li>
          ))}
        </ul>
      </nav>
    </div>
  );
}
