import { cva, type VariantProps } from "class-variance-authority";
import type { HTMLAttributes } from "react";
import { cn } from "@/lib/cn";

const badgeVariants = cva("inline-flex items-center gap-1.5 whitespace-nowrap rounded-full px-2 py-0.5 text-support font-medium", {
  variants: {
    tone: {
      neutral: "bg-surface text-ink-2",
      brand: "bg-brand-light text-brand",
      success: "bg-success-bg text-success",
      warning: "bg-warning-bg text-warning",
      critical: "bg-critical-bg text-critical",
      info: "bg-info-bg text-info",
    },
  },
  defaultVariants: { tone: "neutral" },
});

export type Tone = NonNullable<VariantProps<typeof badgeVariants>["tone"]>;

const dotColor: Record<Tone, string> = { neutral: "bg-ink-3", brand: "bg-brand", success: "bg-success", warning: "bg-warning", critical: "bg-critical", info: "bg-info" };

export function Badge({ tone, dot, className, children, ...props }: HTMLAttributes<HTMLSpanElement> & VariantProps<typeof badgeVariants> & { dot?: boolean }) {
  return (
    <span className={cn(badgeVariants({ tone }), className)} {...props}>
      {dot ? <span className={cn("h-1.5 w-1.5 rounded-full", dotColor[tone ?? "neutral"])} aria-hidden /> : null}
      {children}
    </span>
  );
}
