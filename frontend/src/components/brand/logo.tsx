import { useId } from "react";
import { cn } from "@/lib/cn";

/**
 * The RAGGuard mark. A faceted shield (the guard) holding a check that is drawn as a three-node path: the source, the manifest and
 * the index agreeing. The last node is a ring: the point where a result is verified against the real index.
 * The same drawing lives in public/favicon.svg and docs/assets/logo.svg; keep them in step.
 */
export function LogoMark({ size = 32, className, title }: { size?: number; className?: string; title?: string }) {
  const uid = useId().replace(/[^a-zA-Z0-9]/g, "");
  const grad = `rg-${uid}`;
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 40 40"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      className={className}
      role={title ? "img" : undefined}
      aria-label={title}
      aria-hidden={title ? undefined : true}
      focusable="false"
    >
      <defs>
        <linearGradient id={grad} x1="8" y1="3" x2="33" y2="38" gradientUnits="userSpaceOnUse">
          <stop stopColor="#818CF8" />
          <stop offset="0.5" stopColor="#4F46E5" />
          <stop offset="1" stopColor="#3730A3" />
        </linearGradient>
      </defs>
      <path d="M20 2.6 34 8.2v11c0 8.8-5.6 15.4-14 18.4C11.6 34.6 6 28 6 19.2v-11L20 2.6Z" fill={`url(#${grad})`} />
      <path d="M20 2.6 6 8.2v11c0 8.8 5.6 15.4 14 18.4V2.6Z" fill="#fff" fillOpacity=".12" />
      <path d="M12.4 20.8 17.6 26l9.8-11.8" stroke="#fff" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" />
      <circle cx="12.4" cy="20.8" r="1.9" fill="#fff" />
      <circle cx="17.6" cy="26" r="1.9" fill="#fff" />
      <circle cx="27.4" cy="14.2" r="3.2" fill="#4F46E5" stroke="#fff" strokeWidth="2.2" />
    </svg>
  );
}

/** Mark plus wordmark. `tone="dark"` is for dark backgrounds (white text), `tone="light"` for light ones. */
export function Logo({ tone = "dark", size = 32, className }: { tone?: "dark" | "light"; size?: number; className?: string }) {
  return (
    <span className={cn("inline-flex items-center gap-2.5", className)}>
      <LogoMark size={size} />
      <span className={cn("font-bold leading-none tracking-[-0.02em]", tone === "dark" ? "text-white" : "text-ink")} style={{ fontSize: Math.round(size * 0.56) }}>
        RAG<span className={tone === "dark" ? "text-indigo-300" : "text-brand"}>Guard</span>
      </span>
    </span>
  );
}
