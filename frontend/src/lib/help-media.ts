/**
 * Where the walkthrough video and its files are served from (see frontend/scripts/sync-help-media.mjs).
 * Kept apart from the Help pages' content module so the landing page can show the video without loading the user guide.
 */
export const MEDIA = {
  /** Vercel serves the repo-root public/ folder from its CDN; the serverless function cannot return a file this large. */
  mp4Cdn: "/help-media/RAGGuard-walkthrough.mp4",
  /** Docker and self-hosted servers serve it from the built files. */
  mp4Static: "/static/help-media/RAGGuard-walkthrough.mp4",
  captions: "/static/help-media/RAGGuard-walkthrough.vtt",
  poster: "/static/help-media/RAGGuard-walkthrough-poster.jpg",
} as const;
