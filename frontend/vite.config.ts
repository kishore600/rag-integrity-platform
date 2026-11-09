import react from "@vitejs/plugin-react";
import path from "node:path";
import { defineConfig } from "vite";

// The app is served by the Python backend: assets live under /static/ and the build lands inside the Python package,
// so deploying the backend deploys the interface (no Node build step on Vercel).
export default defineConfig({
  base: "/static/",
  // The repo-root public/ folder: Vercel serves it from its CDN at the root (the Help video needs that), and Vite copies it into
  // the build, so a Docker or self-hosted server serves the same files under /static/.
  publicDir: path.resolve(__dirname, "../public"),
  plugins: [react()],
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
