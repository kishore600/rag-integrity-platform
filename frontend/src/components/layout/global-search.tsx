import { FileText, Search, ShieldAlert } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { cn } from "@/lib/cn";
import { links } from "@/lib/links";

/** Topbar search: choose whether to look in documents or issues. Enter searches documents. Press "/" anywhere to focus it. */
export function GlobalSearch() {
  const [q, setQ] = useState("");
  const [open, setOpen] = useState(false);
  const [cursor, setCursor] = useState(0);
  const input = useRef<HTMLInputElement>(null);
  const box = useRef<HTMLDivElement>(null);
  const navigate = useNavigate();
  // a long placeholder is cut off on a phone: say "Search" there
  const [wide, setWide] = useState(() => window.matchMedia("(min-width: 640px)").matches);
  useEffect(() => {
    const m = window.matchMedia("(min-width: 640px)");
    const f = () => setWide(m.matches);
    m.addEventListener("change", f);
    return () => m.removeEventListener("change", f);
  }, []);

  const term = q.trim();
  const options = [
    { label: "Documents", icon: FileText, go: () => navigate(links.documents({ q: term })) },
    { label: "Integrity issues", icon: ShieldAlert, go: () => navigate(links.issues({ q: term })) },
  ];

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement | null;
      if (e.key === "/" && !(t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.tagName === "SELECT" || t.isContentEditable))) {
        e.preventDefault();
        input.current?.focus();
      }
    };
    const onClick = (e: MouseEvent) => {
      if (box.current && !box.current.contains(e.target as Node)) setOpen(false);
    };
    window.addEventListener("keydown", onKey);
    window.addEventListener("mousedown", onClick);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("mousedown", onClick);
    };
  }, []);

  function choose(i: number) {
    if (!term) return;
    options[i].go();
    setOpen(false);
    setQ("");
    input.current?.blur();
  }

  return (
    <div ref={box} className="relative w-full max-w-md">
      <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-3" aria-hidden />
      <input
        ref={input}
        value={q}
        onChange={(e) => {
          setQ(e.target.value);
          setOpen(true);
          setCursor(0);
        }}
        onFocus={() => setOpen(true)}
        onKeyDown={(e) => {
          if (e.key === "ArrowDown") {
            e.preventDefault();
            setCursor((c) => (c + 1) % options.length);
          } else if (e.key === "ArrowUp") {
            e.preventDefault();
            setCursor((c) => (c - 1 + options.length) % options.length);
          } else if (e.key === "Enter") {
            e.preventDefault();
            choose(cursor);
          } else if (e.key === "Escape") {
            setOpen(false);
            input.current?.blur();
          }
        }}
        placeholder={wide ? "Search documents and issues" : "Search"}
        aria-label="Search documents and issues"
        aria-expanded={open && !!term}
        role="combobox"
        aria-controls="global-search-list"
        className="h-9 w-full rounded-control border border-line bg-app pl-9 pr-9 text-body placeholder:text-ink-3 hover:border-line-strong focus:border-brand focus:bg-white focus:outline-none focus:ring-2 focus:ring-brand/20"
      />
      <kbd className="pointer-events-none absolute right-2.5 top-1/2 hidden -translate-y-1/2 rounded border border-line bg-white px-1.5 text-support text-ink-3 sm:block">/</kbd>
      {open && term ? (
        <ul id="global-search-list" role="listbox" className="anim-pop absolute left-0 right-0 top-full z-40 mt-1.5 rounded-card border border-line bg-workspace p-1 shadow-pop" data-state="open">
          {options.map((o, i) => (
            <li key={o.label} role="option" aria-selected={i === cursor}>
              <button
                type="button"
                onMouseEnter={() => setCursor(i)}
                onClick={() => choose(i)}
                className={cn("flex w-full items-center gap-2.5 rounded-control px-2.5 py-2 text-left text-body", i === cursor ? "bg-surface" : "")}
              >
                <o.icon className="h-4 w-4 text-ink-2" aria-hidden />
                <span className="min-w-0 truncate">
                  Search <span className="font-medium">{o.label}</span> for “{term}”
                </span>
              </button>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
