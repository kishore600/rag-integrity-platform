/**
 * Build-time HTML for the public pages, so that AI assistants and search engines that do not run JavaScript can read them.
 *
 * `npm run build` runs scripts/prerender.mjs, which builds this module for Node and calls renderAll(). Each page is rendered with
 * the same components the browser uses, with their data already in the query cache, so the HTML matches what people see. The
 * server puts a page's HTML inside <div id="root"> for visitors without a session; the app then replaces it as usual.
 * Nothing here runs in the browser.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { Route, Routes, StaticRouter } from "react-router-dom";
import { TooltipProvider } from "@/components/ui/menus";
import { qk } from "@/hooks/queries";
import { GUIDES, GUIDES_README, GuidePage, GuidesIndex } from "@/pages/guides";
import { HelpChapter, HelpHome, HelpPublicLayout } from "@/pages/help";
import { loadIndex, loadMarkdown } from "@/pages/help/content";
import { helpIndexQuery } from "@/pages/help/home";
import Landing from "@/pages/landing";
import LegalPage from "@/pages/legal";
import privacyText from "../../docs/legal/privacy.md?raw";
import termsText from "../../docs/legal/terms.md?raw";
import type { Session } from "@/types/api";

export interface Page {
  path: string;
  title: string;
  description: string;
  html: string;
}

/** What a signed-out visitor's session looks like on a hosted server with sign-up open. */
const SESSION: Session = { app: true, mode: "app", version: "", authenticated: false, registration_open: true, setup: { required: false }, user: null };

const SITE_SUMMARY =
  "RAGGuard checks that a RAG (retrieval-augmented generation) index matches its source documents. It compares the files in Amazon S3 with a " +
  "Qdrant or pgvector index, and optionally the ingestion pipeline's own records, and reports missing, stale, half-indexed, duplicate, empty, " +
  "deleted-but-still-searchable and wrong-tenant chunks, with the evidence and a safe fix. It only reads your systems. Free during the beta.";

/** The signed-out routes of App.tsx, without lazy loading. */
function PublicRoutes() {
  return (
    <Routes>
      <Route index element={<Landing session={SESSION} />} />
      <Route path="help" element={<HelpPublicLayout />}>
        <Route index element={<HelpHome />} />
        <Route path=":chapter" element={<HelpChapter />} />
      </Route>
      <Route element={<HelpPublicLayout />}>
        <Route path="privacy" element={<LegalPage doc="privacy" />} />
        <Route path="terms" element={<LegalPage doc="terms" />} />
        <Route path="guides" element={<GuidesIndex />} />
        <Route path="guides/:slug" element={<GuidePage />} />
      </Route>
    </Routes>
  );
}

function render(path: string, client: QueryClient, routes: ReactNode = <PublicRoutes />): string {
  return renderToStaticMarkup(
    <QueryClientProvider client={client}>
      <StaticRouter location={path}>
        <TooltipProvider>{routes}</TooltipProvider>
      </StaticRouter>
    </QueryClientProvider>,
  );
}

const titleOf = (markdown: string, fallback: string) => /^#\s+(.+?)\s*$/m.exec(markdown)?.[1] ?? fallback;

/** Chapters of the user guide that go into llms-full.txt with the guides (the whole guide is far too long for one AI file). */
const FULL_TEXT_CHAPTERS = ["01-getting-started", "16-use-cases", "18-troubleshooting"];

export async function renderAll(): Promise<{ pages: Page[]; llms: string; llmsFull: string }> {
  const index = await loadIndex();
  const chapters = index.flatMap((g) => g.chapters);
  const client = new QueryClient({ defaultOptions: { queries: { staleTime: Infinity, retry: false } } });
  client.setQueryData(qk.session, SESSION);
  client.setQueryData(helpIndexQuery.queryKey, index);
  const markdown = new Map<string, string>();
  for (const c of chapters) {
    const text = await loadMarkdown(c.slug);
    markdown.set(c.slug, text);
    client.setQueryData(["help", "chapter", c.slug], text);
  }

  const pages: Page[] = [
    { path: "/", title: "RAGGuard: know when your RAG index is wrong, before your users do", description: SITE_SUMMARY, html: "" },
    { path: "/guides", title: `${GUIDES_README.title} · RAGGuard`, description: GUIDES_README.summary, html: "" },
    ...GUIDES.map((g) => ({ path: `/guides/${g.slug}`, title: `${g.title} · RAGGuard`, description: g.summary, html: "" })),
    {
      path: "/help",
      title: "Help and user guide · RAGGuard",
      description: "The RAGGuard user guide: what every page, field and value means and what to do next, with a six-minute walkthrough video.",
      html: "",
    },
    ...chapters.map((c) => ({ path: `/help/${c.slug}`, title: `${c.title} · Help · RAGGuard`, description: c.summary, html: "" })),
    { path: "/privacy", title: "Privacy Policy · RAGGuard", description: "What the hosted RAGGuard service collects, why, who else handles it, how long it is kept and your rights.", html: "" },
    { path: "/terms", title: "Terms of Service · RAGGuard", description: "The terms for using the hosted RAGGuard service during its free beta.", html: "" },
  ];
  for (const p of pages) p.html = render(p.path, client);

  const guideLines = GUIDES.map((g) => `- [${g.title}]({BASE}/guides/${g.slug}): ${g.summary}`);
  const chapterLines = chapters.map((c) => `- [${c.number}. ${c.title}]({BASE}/help/${c.slug}): ${c.summary}`);
  const llms = [
    "# RAGGuard",
    "",
    `> ${SITE_SUMMARY}`,
    "",
    "RAGGuard is a hosted web app with an HTTP API, a command-line tool (`ragguard`) and an MCP server, so AI coding assistants can run its checks. " +
      "It never writes to your storage or index: fixes go to your own worker as signed requests, and old vectors are removed only after you " +
      "approve, unless you switch on automatic clean-up.",
    "",
    "## Guides",
    "",
    `- [${GUIDES_README.title}]({BASE}/guides): ${GUIDES_README.summary}`,
    ...guideLines,
    "",
    "## Product",
    "",
    `- [Home]({BASE}/): what RAGGuard checks, how it works, what it costs, and how it keeps your systems safe`,
    `- [Help and user guide]({BASE}/help): every page of the app explained`,
    "",
    "## User guide",
    "",
    ...chapterLines,
    "",
    "## Optional",
    "",
    `- [Full text of the guides and the key chapters]({BASE}/llms-full.txt)`,
    `- [Privacy Policy]({BASE}/privacy): ${titleOf(privacyText, "Privacy Policy")}`,
    `- [Terms of Service]({BASE}/terms): ${titleOf(termsText, "Terms of Service")}`,
    "",
  ].join("\n");

  const llmsFull = [
    "# RAGGuard",
    "",
    `> ${SITE_SUMMARY}`,
    "",
    "This file holds the full text of the RAGGuard guides and the key chapters of its user guide. Links between files are relative to " +
      "{BASE}/guides or {BASE}/help.",
    "",
    GUIDES_README.text.trim(),
    ...GUIDES.map((g) => g.text.trim()),
    ...FULL_TEXT_CHAPTERS.map((slug) => (markdown.get(slug) ?? "").trim()),
    "",
  ].join("\n\n---\n\n");

  return { pages, llms, llmsFull };
}
