import { useEffect } from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import { Link } from "react-router-dom";
import rehypeSlug from "rehype-slug";
import remarkGfm from "remark-gfm";
// The policy and the terms live in docs/legal as Markdown, so the page and the repository can never disagree.
import privacy from "../../../../docs/legal/privacy.md?raw";
import terms from "../../../../docs/legal/terms.md?raw";
import "@/pages/help/prose.css";

const DOCS = {
  privacy: { title: "Privacy Policy", text: privacy },
  terms: { title: "Terms of Service", text: terms },
} as const;

export type LegalDoc = keyof typeof DOCS;

const components: Components = {
  a({ href, children }) {
    if (href?.startsWith("/")) return <Link to={href}>{children}</Link>;
    return <a href={href}>{children}</a>;
  },
  table({ children }) {
    return (
      <div className="help-table">
        <table>{children}</table>
      </div>
    );
  },
};

/** The Privacy Policy or the Terms of Service: public, and also reachable while signed in. Raw HTML is never rendered. */
export default function LegalPage({ doc }: { doc: LegalDoc }) {
  const { title, text } = DOCS[doc];
  useEffect(() => {
    const previous = document.title;
    document.title = `${title} · RAGGuard`;
    return () => {
      document.title = previous;
    };
  }, [title]);
  return (
    <article className="help-prose mx-auto py-4">
      <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeSlug]} components={components}>
        {text}
      </ReactMarkdown>
    </article>
  );
}
