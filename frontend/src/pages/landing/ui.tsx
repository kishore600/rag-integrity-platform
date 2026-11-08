import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { cn } from "@/lib/cn";

export const Container = ({ children, className }: { children: ReactNode; className?: string }) => (
  <div className={cn("mx-auto w-full max-w-6xl px-5 sm:px-8", className)}>{children}</div>
);

export function SectionHeading({ eyebrow, title, children, tone = "light", align = "left", id }: { eyebrow: string; title: ReactNode; children?: ReactNode; tone?: "light" | "dark"; align?: "left" | "center"; id: string }) {
  return (
    <div className={cn("max-w-2xl", align === "center" && "mx-auto text-center")}>
      <p className={cn("text-support font-semibold uppercase tracking-[0.14em]", tone === "dark" ? "text-indigo-300" : "text-brand")}>{eyebrow}</p>
      <h2 id={id} className={cn("mt-3 text-[28px] font-bold leading-tight tracking-tight sm:text-[34px]", tone === "dark" ? "text-white" : "text-ink")}>
        {title}
      </h2>
      {children ? <p className={cn("mt-4 text-[16px] leading-7", tone === "dark" ? "text-slate-300" : "text-ink-2")}>{children}</p> : null}
    </div>
  );
}

const cta = "inline-flex h-12 items-center justify-center gap-2 rounded-control px-6 text-body font-semibold transition-colors";

export const CtaPrimary = ({ to, children }: { to: string; children: ReactNode }) => (
  <Link to={to} className={cn(cta, "bg-brand text-white shadow-[0_8px_28px_rgba(79,70,229,0.4)] hover:bg-brand-hover")}>
    {children}
  </Link>
);

export const CtaGhost = ({ to, children }: { to: string; children: ReactNode }) => (
  <Link to={to} className={cn(cta, "border border-white/15 bg-white/5 text-white hover:bg-white/10")}>
    {children}
  </Link>
);
