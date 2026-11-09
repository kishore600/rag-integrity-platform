import { Play } from "lucide-react";
import { useRef, useState } from "react";
import { cn } from "@/lib/cn";
import { MEDIA } from "./content";

/**
 * Where each part of the video starts, in seconds. These match the table in docs/user-guide/19-video-walkthrough.md
 * (tests/test_help_pages.py fails when they differ).
 */
export const VIDEO_CHAPTERS = [
  { t: 0, title: "Introduction" },
  { t: 31, title: "The Documents page" },
  { t: 126, title: "The Isolation page" },
  { t: 233, title: "When the check is limited" },
  { t: 305, title: "Summary" },
] as const;

const clock = (s: number) => `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;

/** The narrated walkthrough, with captions and a button for each part. */
export function HelpVideo() {
  const video = useRef<HTMLVideoElement>(null);
  const [now, setNow] = useState(0);
  const current = [...VIDEO_CHAPTERS].reverse().find((c) => now >= c.t)?.title;

  function seek(t: number) {
    const v = video.current;
    if (!v) return;
    v.currentTime = t;
    void v.play().catch(() => undefined);
  }

  return (
    <div>
      <video
        ref={video}
        controls
        preload="metadata"
        poster={MEDIA.poster}
        onTimeUpdate={(e) => setNow(e.currentTarget.currentTime)}
        className="aspect-video w-full rounded-card border border-line bg-night"
        aria-label="RAGGuard walkthrough: the Documents page and the Isolation page"
      >
        {/* The CDN copy first (Vercel); the copy inside the built files for Docker and self-hosted servers. */}
        <source src={MEDIA.mp4Cdn} type="video/mp4" />
        <source src={MEDIA.mp4Static} type="video/mp4" />
        <track kind="captions" src={MEDIA.captions} srcLang="en" label="English" />
        Your browser cannot play this video. <a href={MEDIA.mp4Cdn}>Download it</a>.
      </video>
      <ul className="mt-3 flex flex-wrap gap-2" aria-label="Parts of the video">
        {VIDEO_CHAPTERS.map((c) => (
          <li key={c.t}>
            <button
              type="button"
              onClick={() => seek(c.t)}
              aria-current={current === c.title ? "true" : undefined}
              className={cn(
                "inline-flex h-8 items-center gap-1.5 rounded-control border px-3 text-support font-medium transition-colors",
                current === c.title ? "border-brand/30 bg-brand-light text-brand" : "border-line bg-workspace text-ink-2 hover:bg-surface hover:text-ink",
              )}
            >
              <Play className="h-3 w-3" aria-hidden />
              <span className="tabular-nums">{clock(c.t)}</span>
              {c.title}
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
