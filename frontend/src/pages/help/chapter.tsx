import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, ArrowRight, BookOpen, Compass } from "lucide-react";
import { useEffect, useMemo, useRef } from "react";
import { Link, useLocation, useNavigate, useParams } from "react-router-dom";
import { LinkButton } from "@/components/shared/link-button";
import { ErrorState, EmptyState, Skeleton } from "@/components/shared/states";
import { cn } from "@/lib/cn";
import { hasChapter, loadMarkdown, type Chapter, type ChapterGroup } from "./content";
import { helpIndexQuery } from "./home";
import { GuideMarkdown } from "./markdown";

function ChapterNav({ groups, current }: { groups: ChapterGroup[]; current: string }) {
  const navigate = useNavigate();
  return (
    <>
      {/* phones and tablets: one control that lists every chapter */}
      <div className="mb-6 lg:hidden">
        <label htmlFor="help-chapter" className="mb-1 block text-support font-medium text-ink-2">
          Chapter
        </label>
        <select
          id="help-chapter"
          value={current}
          onChange={(e) => navigate(e.target.value === "" ? "/help" : `/help/${e.target.value}`)}
          className="h-10 w-full rounded-control border border-line bg-workspace px-3 text-body text-ink"
        >
          <option value="">Contents</option>
          {groups.map((g) => (
            <optgroup key={g.title} label={g.title}>
              {g.chapters.map((c) => (
                <option key={c.slug} value={c.slug}>
                  {c.number}. {c.title}
                </option>
              ))}
            </optgroup>
          ))}
        </select>
      </div>

      <nav aria-label="Guide chapters" className="hidden lg:sticky lg:top-6 lg:block lg:max-h-[calc(100vh-7rem)] lg:self-start lg:overflow-y-auto lg:pr-2">
        <Link to="/help" className="mb-4 inline-flex items-center gap-2 text-body font-medium text-ink-2 hover:text-ink">
          <BookOpen className="h-4 w-4" aria-hidden /> Help contents
        </Link>
        {groups.map((g) => (
          <div key={g.title} className="mb-5">
            <p className="mb-1.5 text-support font-semibold uppercase tracking-wide text-ink-3">{g.title}</p>
            <ul className="space-y-0.5">
              {g.chapters.map((c) => (
                <li key={c.slug}>
                  <Link
                    to={`/help/${c.slug}`}
                    aria-current={c.slug === current ? "page" : undefined}
                    className={cn(
                      "flex gap-2 rounded-control px-2.5 py-1.5 text-body transition-colors",
                      c.slug === current ? "bg-brand-light font-medium text-brand" : "text-ink-2 hover:bg-surface hover:text-ink",
                    )}
                  >
                    <span className="w-5 shrink-0 tabular-nums text-ink-3">{c.number}</span>
                    <span>{c.title}</span>
                  </Link>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </nav>
    </>
  );
}

function Pager({ prev, next }: { prev?: Chapter; next?: Chapter }) {
  return (
    <nav aria-label="Next and previous chapter" className="mt-12 flex max-w-3xl flex-wrap justify-between gap-3 border-t border-line pt-6">
      {prev ? (
        <LinkButton to={`/help/${prev.slug}`} variant="secondary">
          <ArrowLeft className="h-4 w-4" aria-hidden /> {prev.number}. {prev.title}
        </LinkButton>
      ) : (
        <span />
      )}
      {next ? (
        <LinkButton to={`/help/${next.slug}`} variant="secondary">
          {next.number}. {next.title} <ArrowRight className="h-4 w-4" aria-hidden />
        </LinkButton>
      ) : null}
    </nav>
  );
}

/** Keeps a link to a heading working: screenshots above it load late and would push the heading out of view. */
function useScrollToHash(ready: boolean, chapter: string) {
  const { hash } = useLocation();
  const article = useRef<HTMLElement>(null);
  useEffect(() => {
    if (!ready) return;
    const id = decodeURIComponent(hash.slice(1));
    const target = () => (id ? document.getElementById(id) : null);
    if (!id) {
      document.getElementById("main")?.scrollTo({ top: 0 });
      window.scrollTo({ top: 0 });
      return;
    }
    target()?.scrollIntoView({ block: "start" });
    const started = Date.now();
    const again = () => {
      if (Date.now() - started < 4000) target()?.scrollIntoView({ block: "start" });
    };
    const images = Array.from(article.current?.querySelectorAll("img") ?? []).filter((img) => !img.complete);
    images.forEach((img) => img.addEventListener("load", again, { once: true }));
    return () => images.forEach((img) => img.removeEventListener("load", again));
  }, [ready, hash, chapter]);
  return article;
}

export function HelpChapter() {
  const { chapter = "" } = useParams();
  const known = hasChapter(chapter);
  const index = useQuery(helpIndexQuery);
  const doc = useQuery({ queryKey: ["help", "chapter", chapter], queryFn: () => loadMarkdown(chapter), enabled: known, staleTime: Infinity });
  const article = useScrollToHash(!!doc.data, chapter);

  const flat = useMemo(() => (index.data ?? []).flatMap((g) => g.chapters), [index.data]);
  const at = flat.findIndex((c) => c.slug === chapter);
  const current = at >= 0 ? flat[at] : undefined;

  useEffect(() => {
    const previous = document.title;
    if (current) document.title = `${current.title} · Help · RAGGuard`;
    return () => {
      document.title = previous;
    };
  }, [current]);

  if (!known) {
    return (
      <EmptyState
        icon={Compass}
        title="That chapter doesn't exist"
        description="The address doesn't match a chapter of the user guide."
        action={
          <LinkButton variant="primary" to="/help">
            Back to Help
          </LinkButton>
        }
      />
    );
  }

  return (
    <div className="lg:grid lg:grid-cols-[240px_minmax(0,1fr)] lg:gap-12">
      <ChapterNav groups={index.data ?? []} current={chapter} />
      <article ref={article} className="min-w-0" aria-busy={doc.isPending}>
        {doc.isPending ? (
          <div className="max-w-3xl space-y-3">
            <Skeleton className="h-9 w-72" />
            <Skeleton className="h-4 w-full" />
            <Skeleton className="h-4 w-5/6" />
            <Skeleton className="h-64" />
          </div>
        ) : doc.isError ? (
          <ErrorState error={doc.error} onRetry={() => void doc.refetch()} />
        ) : (
          <>
            <GuideMarkdown text={doc.data} />
            <Pager prev={at > 0 ? flat[at - 1] : undefined} next={at >= 0 && at < flat.length - 1 ? flat[at + 1] : undefined} />
          </>
        )}
      </article>
    </div>
  );
}
