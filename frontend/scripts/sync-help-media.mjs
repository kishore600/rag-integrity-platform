/**
 * Copies the walkthrough video, its captions and its poster from docs/user-guide/video into public/help-media.
 *
 * Why a copy: Vercel serves a root `public/` folder from its CDN, and that is the only way to serve the 8 MB video there (the
 * app's own files go through the serverless function, which cannot return more than 4.5 MB). Vite copies the same folder into
 * src/ragintegrity/api/static, so a Docker or self-hosted server serves it under /static/help-media/ as well.
 * Runs before every `npm run build`; the docs folder stays the one place the files are edited.
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(here, "..", "..");
const from = path.join(root, "docs", "user-guide", "video");
const to = path.join(root, "public", "help-media");
const FILES = ["RAGGuard-walkthrough.mp4", "RAGGuard-walkthrough.vtt", "RAGGuard-walkthrough-poster.jpg"];

fs.mkdirSync(to, { recursive: true });
for (const name of FILES) {
  const src = path.join(from, name);
  if (!fs.existsSync(src)) throw new Error(`Missing ${path.relative(root, src)}: the Help page plays this file.`);
  const dst = path.join(to, name);
  const same = fs.existsSync(dst) && fs.statSync(dst).size === fs.statSync(src).size && fs.readFileSync(dst).equals(fs.readFileSync(src));
  if (!same) fs.copyFileSync(src, dst);
}
console.log(`help media: ${FILES.length} files in public/help-media`);
