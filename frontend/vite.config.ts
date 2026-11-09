import react from "@vitejs/plugin-react";
import fs from "node:fs";
import path from "node:path";
import { defineConfig, type Plugin } from "vite";

/**
 * The Help pages embed the Markdown of docs/user-guide as text. Git on Windows can check files out with CRLF line endings
 * (core.autocrlf), CI checks them out with LF, and the committed build must be byte-identical in both (CI compares them). So the
 * text is read here with LF endings, whatever is on disk.
 */
function lfMarkdown(): Plugin {
  return {
    name: "lf-markdown",
    enforce: "pre",
    load(id) {
      if (!id.endsWith(".md?raw")) return null;
      const file = id.slice(0, -"?raw".length);
      this.addWatchFile(file);
      return `export default ${JSON.stringify(fs.readFileSync(file, "utf8").replace(/\r\n/g, "\n"))};`;
    },
  };
}

// The app is served by the Python backend: assets live under /static/ and the build lands inside the Python package,
// so deploying the backend deploys the interface (no Node build step on Vercel).
export default defineConfig({
  base: "/static/",
  // The repo-root public/ folder: Vercel serves it from its CDN at the root (the Help video needs that), and Vite copies it into
  // the build, so a Docker or self-hosted server serves the same files under /static/.
  publicDir: path.resolve(__dirname, "../public"),
  plugins: [lfMarkdown(), react()],
  resolve: { alias: { "@": path.resolve(__dirname, "src") } },
  build: {
    outDir: path.resolve(__dirname, "../src/ragintegrity/api/static"),
    emptyOutDir: true,
    sourcemap: false,
    chunkSizeWarningLimit: 900,
  },
  server: {
    port: 5173,
    // The Help pages read the user guide from ../docs/user-guide
    fs: { allow: [path.resolve(__dirname, "..")] },
    // `npm run dev` talks to a locally running backend: ragi serve --app  (or --demo)
    proxy: { "/api": "http://127.0.0.1:8000", "/healthz": "http://127.0.0.1:8000" },
  },
});
