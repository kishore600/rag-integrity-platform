import { Suspense } from "react";
import { Link, Outlet } from "react-router-dom";
import { Logo } from "@/components/brand/logo";
import { Skeleton } from "@/components/shared/states";
import { useSession } from "@/hooks/queries";

const link = "inline-flex h-10 items-center whitespace-nowrap rounded-control px-3 text-body font-medium transition-colors sm:px-4";

/** The Help pages for someone who is not signed in: the guide and the video are public, the product is not. */
export function HelpPublicLayout() {
  const registrationOpen = useSession().data?.registration_open;
  return (
    <div className="min-h-full bg-app">
      <header className="border-b border-white/5 bg-night">
        <div className="mx-auto flex h-16 w-full max-w-[1440px] items-center justify-between gap-3 px-4 sm:px-6 lg:px-8">
          <Link to="/" aria-label="RAGGuard home" className="shrink-0 rounded-control">
            <Logo size={32} />
          </Link>
          <nav aria-label="Account" className="flex items-center gap-1 sm:gap-2">
            <Link to="/login" className={`${link} text-slate-200 hover:bg-white/10 hover:text-white`}>
              Sign in
            </Link>
            {registrationOpen ? (
              <Link to="/signup" className={`${link} bg-brand font-semibold text-white hover:bg-brand-hover`}>
                Get started
              </Link>
            ) : null}
          </nav>
        </div>
      </header>
      <main id="main" className="mx-auto w-full max-w-[1440px] px-4 py-6 sm:px-6 lg:px-8">
        <Suspense fallback={<Skeleton className="h-64" />}>
          <Outlet />
        </Suspense>
      </main>
    </div>
  );
}
