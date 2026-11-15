import { AlertTriangle, Inbox, RefreshCw, Sparkles, type LucideIcon } from "lucide-react";
import type { ReactNode } from "react";
import type { UseQueryResult } from "@tanstack/react-query";
import { LinkButton } from "./link-button";
import { ApiError, errorMessage } from "@/lib/api";
import { cn } from "@/lib/cn";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";

export const Skeleton = ({ className }: { className?: string }) => <div className={cn("skeleton", className)} aria-hidden />;

export function EmptyState({ icon: Icon = Inbox, title, description, action, className, compact }: { icon?: LucideIcon; title: string; description?: ReactNode; action?: ReactNode; className?: string; compact?: boolean }) {
  return (
    <div className={cn("flex flex-col items-center justify-center text-center", compact ? "px-4 py-8" : "px-6 py-14", className)}>
      <div className="mb-3 flex h-11 w-11 items-center justify-center rounded-full bg-surface text-ink-2">
        <Icon className="h-5 w-5" aria-hidden />
      </div>
      <h3 className="text-section text-ink">{title}</h3>
      {description ? <p className="mt-1 max-w-md text-body text-ink-2">{description}</p> : null}
      {action ? <div className="mt-4">{action}</div> : null}
    </div>
  );
}

/** A failed request. If the server says a connection still has to be configured, the next step is offered instead of a stack of text. */
export function ErrorState({ error, onRetry, className, compact }: { error: unknown; onRetry?: () => void; className?: string; compact?: boolean }) {
  const setup = error instanceof ApiError && error.setupIncomplete;
  return (
    <div className={cn("flex flex-col items-center justify-center text-center", compact ? "px-4 py-8" : "px-6 py-14", className)} role="alert">
      <div className={cn("mb-3 flex h-11 w-11 items-center justify-center rounded-full", setup ? "bg-brand-light text-brand" : "bg-critical-bg text-critical")}>
        {setup ? <Sparkles className="h-5 w-5" aria-hidden /> : <AlertTriangle className="h-5 w-5" aria-hidden />}
      </div>
      <h3 className="text-section text-ink">{setup ? "Connect your data sources first" : "We couldn't load this"}</h3>
      <p className="mt-1 max-w-md text-body text-ink-2">{setup ? "RAGGuard needs your S3 source and your vector index before it can compare them." : errorMessage(error)}</p>
      <div className="mt-4 flex gap-2">
        {setup ? <LinkButton variant="primary" to="/data-sources">Go to Data Sources</LinkButton> : null}
        {onRetry && !setup ? (
          <Button variant="secondary" onClick={onRetry}>
            <RefreshCw className="h-4 w-4" /> Try again
          </Button>
        ) : null}
      </div>
    </div>
  );
}

/** Loading → skeleton, error → ErrorState, otherwise the render prop gets the data. Keeps every page's three states identical. */
export function QueryState<T, E = unknown>({ query, skeleton, children, compact }: { query: UseQueryResult<T, E>; skeleton?: ReactNode; children: (data: T) => ReactNode; compact?: boolean }) {
  if (query.isPending) return <>{skeleton ?? <Skeleton className="h-40 w-full" />}</>;
  if (query.isError) return <ErrorState error={query.error} onRetry={() => void query.refetch()} compact={compact} />;
  return <>{children(query.data)}</>;
}

/** A feature the product does not have yet. Shown honestly instead of as a dead control or fake data. */
export function NotAvailable({ title, description, className }: { title: string; description?: ReactNode; className?: string }) {
  return (
    <Card className={cn("border-dashed bg-app p-5 shadow-none", className)}>
      <div className="flex flex-wrap items-center gap-2">
        <h3 className="text-card text-ink">{title}</h3>
        <Badge tone="neutral">Not available yet</Badge>
      </div>
      {description ? <p className="mt-1.5 text-body text-ink-2">{description}</p> : null}
    </Card>
  );
}
