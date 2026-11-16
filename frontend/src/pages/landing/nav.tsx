import { Link } from "react-router-dom";
import { Logo } from "@/components/brand/logo";
import { AUDIT_MAILTO, CONTACT_MAILTO } from "./contact";
import { Container } from "./ui";

const LINKS = [
  { href: "#how", label: "How it works" },
  { href: "#scenarios", label: "Scenarios" },
  { href: "#use-cases", label: "Use cases" },
  { href: "#security", label: "Security" },
  { href: "#faq", label: "FAQ" },
];

export function LandingNav({ canRegister }: { canRegister: boolean }) {
  return (
    <header className="sticky top-0 z-40 border-b border-white/5 bg-night/80 backdrop-blur-md">
      <Container className="flex h-16 items-center justify-between gap-3 sm:gap-6">
        <Link to="/" aria-label="RAGGuard home" className="shrink-0 rounded-control">
          <Logo size={32} />
        </Link>
        <nav aria-label="Page sections" className="hidden items-center gap-7 md:flex">
          {LINKS.map((l) => (
            <a key={l.href} href={l.href} className="text-body font-medium text-slate-300 transition-colors hover:text-white">
              {l.label}
            </a>
          ))}
          <Link to="/guides" className="text-body font-medium text-slate-300 transition-colors hover:text-white">
            Guides
          </Link>
          <Link to="/help" className="text-body font-medium text-slate-300 transition-colors hover:text-white">
            User guide
          </Link>
        </nav>
        <div className="flex items-center gap-1 sm:gap-2">
          <Link to="/login" className="inline-flex h-10 items-center whitespace-nowrap rounded-control px-3 text-body font-medium text-slate-200 transition-colors hover:bg-white/10 hover:text-white sm:px-4">
            Sign in
          </Link>
          {canRegister ? (
            <Link to="/signup" className="inline-flex h-10 items-center whitespace-nowrap rounded-control bg-brand px-3 text-body font-semibold text-white transition-colors hover:bg-brand-hover sm:px-4">
              Get started
            </Link>
          ) : null}
        </div>
      </Container>
    </header>
  );
}

export function LandingFooter({ canRegister }: { canRegister: boolean }) {
  return (
    <footer className="border-t border-white/5 bg-night text-slate-400">
      <Container className="flex flex-col gap-8 py-12 md:flex-row md:items-start md:justify-between">
        <div className="max-w-xs">
          <Logo size={32} />
          <p className="mt-4 text-body leading-6">An independent verifier for retrieval-augmented generation. Know when your index is wrong, before your users do.</p>
        </div>
        <nav aria-label="Footer" className="flex flex-wrap gap-x-10 gap-y-3 text-body">
          <Link to="/login" className="hover:text-white">Sign in</Link>
          {canRegister ? <Link to="/signup" className="hover:text-white">Create account</Link> : null}
          <a href="#faq" className="hover:text-white">FAQ</a>
          <Link to="/guides" className="hover:text-white">Guides</Link>
          <Link to="/help" className="hover:text-white">User guide</Link>
          <a href={AUDIT_MAILTO} className="hover:text-white">Book a free audit</a>
          <a href={CONTACT_MAILTO} className="hover:text-white">Contact</a>
          <Link to="/privacy" className="hover:text-white">Privacy</Link>
          <Link to="/terms" className="hover:text-white">Terms</Link>
        </nav>
      </Container>
      <div className="border-t border-white/5">
        <Container className="py-5 text-support text-slate-500">© {new Date().getFullYear()} RAGGuard. All rights reserved.</Container>
      </div>
    </footer>
  );
}
