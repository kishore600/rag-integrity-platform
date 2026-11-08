import { CopyButton } from "@/components/shared/copy-button";
import { cn } from "@/lib/cn";

/** A snippet the reader is meant to copy. It scrolls sideways on narrow screens instead of breaking the layout. */
export function CodeBlock({ code, label, className }: { code: string; label: string; className?: string }) {
  return (
    <div className={cn("overflow-hidden rounded-control border border-line bg-surface", className)}>
      <div className="flex items-center justify-between gap-3 border-b border-line px-3 py-1.5">
        <span className="text-support text-ink-2">{label}</span>
        <CopyButton text={code} label="Copy" />
      </div>
      <pre className="overflow-x-auto p-3 font-mono text-support leading-5 text-ink" tabIndex={0}>
        <code>{code}</code>
      </pre>
    </div>
  );
}
