import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { Card } from "@/components/ui/card";
import { PageHeader } from "@/components/shared/page";
import { ErrorState, Skeleton } from "@/components/shared/states";
import { loadIndex } from "./content";
import { HelpVideo } from "./video";

export const helpIndexQuery = { queryKey: ["help", "index"], queryFn: loadIndex, staleTime: Infinity } as const;

/** The Help start page: the video, then every chapter of the user guide grouped the way the written guide groups them. */
export function HelpHome() {
  const index = useQuery(helpIndexQuery);
  return (
    <div>
      <PageHeader
        title="Help and user guide"
        description="Watch the walkthrough, or read a chapter for every page: what each section, field and value means, and what to do next."
      />

      <Card className="mb-10 max-w-4xl p-5">
        <h2 className="text-section">Video walkthrough</h2>
        <p className="mb-4 mt-1 text-body text-ink-2">About six minutes, narrated, with captions. It shows the Documents page and the Isolation page on a demo workspace. Use the buttons to jump to a part.</p>
        <HelpVideo />
      </Card>

      {index.isPending ? (
        <div className="space-y-3" aria-busy>
          <Skeleton className="h-6 w-40" />
          <Skeleton className="h-24" />
        </div>
      ) : index.isError ? (
        <ErrorState error={index.error} onRetry={() => void index.refetch()} />
      ) : (
        <div className="space-y-10">
          {index.data.map((group) => (
            <section key={group.title} aria-labelledby={`g-${group.title}`}>
              <h2 id={`g-${group.title}`} className="mb-3 text-section">
                {group.title}
              </h2>
              <ul className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
                {group.chapters.map((c) => (
                  <li key={c.slug}>
                    <Link to={`/help/${c.slug}`} className="flex h-full gap-3 rounded-card border border-line bg-workspace p-4 shadow-card transition-colors hover:border-brand/40 hover:bg-brand-light/40">
                      <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-control bg-brand-light text-support font-semibold tabular-nums text-brand" aria-hidden>
                        {c.number}
                      </span>
                      <span className="min-w-0">
                        <span className="block text-card text-ink">{c.title}</span>
                        <span className="mt-0.5 block text-body text-ink-2">{c.summary}</span>
                      </span>
                    </Link>
                  </li>
                ))}
              </ul>
            </section>
          ))}
        </div>
      )}
    </div>
  );
}
