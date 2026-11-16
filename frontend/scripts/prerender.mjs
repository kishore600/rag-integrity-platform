/**
 * Writes the build-time HTML of the public pages (see src/prerender.tsx) into the committed build:
 *
 *   src/ragintegrity/api/static/prerender/<page>.html   the HTML that goes inside <div id="root"> for that page
 *   src/ragintegrity/api/static/prerender/pages.json    path -> file, title and description, read by the server
 *   src/ragintegrity/api/static/llms.txt                the llms.txt index for AI assistants ({BASE} is filled in by the server)
 *   src/ragintegrity/api/static/llms-full.txt           the full text of the guides and key chapters
 *
 * Runs after `vite build` (which empties the folder first). The output must be byte-identical on Windows and in CI.
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { build } from "vite";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const out = path.resolve(root, "../src/ragintegrity/api/static");
const tmp = path.resolve(root, "node_modules/.ragguard-prerender");

await build({
  root,
  logLevel: "warn",
  publicDir: false,
  build: {
    ssr: "src/prerender.tsx",
    outDir: tmp,
    emptyOutDir: true,
    copyPublicDir: false,
    rollupOptions: { output: { entryFileNames: "prerender.mjs", format: "es" } },
  },
});

const { renderAll } = await import(pathToFileURL(path.join(tmp, "prerender.mjs")).href);
const { pages, llms, llmsFull } = await renderAll();

const dir = path.join(out, "prerender");
fs.rmSync(dir, { recursive: true, force: true });
fs.mkdirSync(dir, { recursive: true });

const fileFor = (p) => (p === "/" ? "home.html" : `${p.slice(1).replace(/\//g, "__")}.html`);
const manifest = {};
for (const page of [...pages].sort((a, b) => a.path.localeCompare(b.path))) {
  const file = fileFor(page.path);
  fs.writeFileSync(path.join(dir, file), page.html, "utf8");
  manifest[page.path] = { file, title: page.title, description: page.description };
}
fs.writeFileSync(path.join(dir, "pages.json"), JSON.stringify(manifest, null, 2) + "\n", "utf8");
fs.writeFileSync(path.join(out, "llms.txt"), llms.replace(/\r\n/g, "\n"), "utf8");
fs.writeFileSync(path.join(out, "llms-full.txt"), llmsFull.replace(/\r\n/g, "\n"), "utf8");
fs.rmSync(tmp, { recursive: true, force: true });

console.log(`prerendered ${pages.length} pages, llms.txt and llms-full.txt`);
