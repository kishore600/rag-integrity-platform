import { isValidElement, useMemo, type ReactNode } from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import { Link } from "react-router-dom";
import rehypeSlug from "rehype-slug";
import remarkGfm from "remark-gfm";
import { CopyButton } from "@/components/shared/copy-button";
import { MEDIA, hasChapter, imageUrl } from "./content";
import "./prose.css";

const PLUGINS = [remarkGfm];
const REHYPE = [rehypeSlug];

const textOf = (node: ReactNode): string => {
  if (typeof node === "string" || typeof node === "number") return String(node);
  if (Array.isArray(node)) return node.map(textOf).join("");
  if (isValidElement(node)) return textOf((node.props as { children?: ReactNode }).children);
  return "";
};

/** Where a link in the Markdown goes: an app route, an outside address, an anchor on the page, or nowhere (a repository file). */
export interface ResolvedHref {
  to?: string;
  external?: string;
  native?: string;
  unavailable?: boolean;
}

/** `20-isolation.md#the-limited-state` -> /help/20-isolation#the-limited-state. Files outside the guide are not part of the app. */
function resolve(href: string): ResolvedHref {
  if (href.startsWith("#")) return { native: href };
  if (/^(https?:|mailto:)/i.test(href)) return { external: href };
  const [path, fragment] = href.split("#");
  const frag = fragment ? `#${fragment}` : "";
  if (path === "video/RAGGuard-walkthrough.mp4") return { to: "/help" }; // the player is on the Help start page
  if (path === "video/RAGGuard-walkthrough.vtt") return { native: MEDIA.captions };
  if (path === "README.md") return { to: `/help${frag}` };
  const m = /^([\w-]+)\.md$/.exec(path);
  if (m && hasChapter(m[1])) return { to: `/help/${m[1]}${frag}` };
  return { unavailable: true }; // GUIDE.md, README.md in the repository root, other docs: they live in the repository
}

const makeComponents = (resolveHref: (href: string) => ResolvedHref): Components => ({
  a({ href, children }) {
    if (!href) return <span>{children}</span>;
    const r = resolveHref(href);
    if (r.to) return <Link to={r.to}>{children}</Link>;
    if (r.external) return <a href={r.external} target="_blank" rel="noopener noreferrer">{children}</a>;
    if (r.native) return <a href={r.native}>{children}</a>;
    return (
      <span className="help-offsite" title="This reference lives in the project repository, not in the app.">
        {children}
      </span>
    );
  },
  img({ src, alt }) {
    const url = src ? imageUrl(src) : undefined;
    if (!url) return <span className="help-offsite">[{alt || "image"}]</span>;
    // Every screenshot is 1440 by 810 except the phone one (780 by 1688). The sizes reserve the space, so lazy loading does not
    // make the page jump (tests/test_help_pages.py checks the sizes).
    const phone = /(^|\/)mobile-/.test(src ?? "");
    return (
      <a href={url} target="_blank" rel="noopener noreferrer" className={phone ? "help-figure help-figure-phone" : "help-figure"} title="Open the full-size picture">
        <img src={url} alt={alt ?? ""} width={phone ? 780 : 1440} height={phone ? 1688 : 810} loading="lazy" decoding="async" />
      </a>
    );
  },
  table({ children }) {
    return (
      <div className="help-table">
        <table>{children}</table>
      </div>
    );
  },
  pre({ children }) {
    const text = textOf(children).replace(/\n$/, "");
    return (
      <div className="help-code">
        <pre>{children}</pre>
        <div className="help-code-copy">
          <CopyButton text={text} />
        </div>
      </div>
    );
  },
});

const components = makeComponents(resolve);

/**
 * One chapter of the guide, styled with the product's own tokens. Raw HTML is never rendered. `resolveHref` replaces the user guide's
 * own link rules, for other Markdown shown the same way (the how-to guides).
 */
export function GuideMarkdown({ text, resolveHref }: { text: string; resolveHref?: (href: string) => ResolvedHref }) {
  const custom = useMemo(() => (resolveHref ? makeComponents(resolveHref) : null), [resolveHref]);
  return (
    <div className="help-prose">
      <ReactMarkdown remarkPlugins={PLUGINS} rehypePlugins={REHYPE} components={custom ?? components}>
        {text}
      </ReactMarkdown>
    </div>
  );
}
