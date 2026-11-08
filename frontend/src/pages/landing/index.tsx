import { useEffect } from "react";
import type { Session } from "@/types/api";
import { Hero } from "./hero";
import { LandingFooter, LandingNav } from "./nav";
import { Detects, Faq, FinalCta, Features, HowItWorks, Problem, Security, Stack } from "./sections";

/** What a signed-out visitor sees at "/". Everything on it is true of the product; there are no invented customers or numbers. */
export default function Landing({ session }: { session: Session }) {
  const canRegister = !!session.registration_open;
  useEffect(() => {
    const previous = document.title;
    document.title = "RAGGuard: know when your RAG index is wrong, before your users do";
    return () => {
      document.title = previous;
    };
  }, []);
  return (
    <div className="min-h-full bg-night">
      <a href="#main" className="sr-only focus:not-sr-only focus:fixed focus:left-3 focus:top-3 focus:z-[70] focus:rounded-control focus:bg-brand focus:px-3 focus:py-2 focus:text-white">
        Skip to content
      </a>
      <LandingNav canRegister={canRegister} />
      <main id="main">
        <Hero canRegister={canRegister} />
        <Problem />
        <HowItWorks />
        <Detects />
        <Features />
        <Security />
        <Stack />
        <Faq />
        <FinalCta canRegister={canRegister} />
      </main>
      <LandingFooter canRegister={canRegister} />
    </div>
  );
}
