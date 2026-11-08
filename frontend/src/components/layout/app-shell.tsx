import * as Dialog from "@radix-ui/react-dialog";
import { Info } from "lucide-react";
import { Suspense, useEffect, useRef, useState } from "react";
import { Outlet, useLocation } from "react-router-dom";
import { toast } from "sonner";
import { useQueryClient } from "@tanstack/react-query";
import { Skeleton } from "@/components/shared/states";
import { invalidateData, useOverview, useSession } from "@/hooks/queries";
import { Sidebar, SidebarContent } from "./sidebar";
import { Topbar } from "./topbar";

/** Honest labelling: the single-user demo server runs on synthetic data, so say so on every screen. */
function DemoBanner() {
  const demo = useSession().data?.demo;
  if (!demo) return null;
  return (
    <div className="mb-5 flex items-start gap-2.5 rounded-card border border-warning/30 bg-warning-bg px-4 py-3 text-body text-ink" role="note">
      <Info className="mt-0.5 h-4 w-4 shrink-0 text-warning" aria-hidden />
      <p>
        <span className="font-semibold">Demo data.</span> This server is running a synthetic knowledge base so you can explore the product. Nothing here comes from your own systems.
      </p>
    </div>
  );
}

/** Notices when a background audit finishes, so the user is told even if they are on another page. */
function AuditWatcher() {
  const qc = useQueryClient();
  const session = useSession().data;
  const overview = useOverview(session ? (session.app ? !!session.ready : true) : false).data;
  const was = useRef<boolean | null>(null);
  useEffect(() => {
    if (!overview) return;
    if (was.current === true && !overview.audit_running) {
      void invalidateData(qc);
      const run = overview.latest_run;
      if (run?.status === "failed") toast.error("Audit failed", { description: run.error ?? "See Audit History for details." });
      else toast.success("Audit finished", { description: `${overview.issues.open} open issue${overview.issues.open === 1 ? "" : "s"}.` });
    }
    was.current = overview.audit_running;
  }, [overview, qc]);
  return null;
}

function PageFallback() {
  return (
    <div className="space-y-4" aria-busy>
      <Skeleton className="h-8 w-56" />
      <Skeleton className="h-4 w-96 max-w-full" />
      <div className="grid grid-cols-1 gap-4 pt-4 sm:grid-cols-2 xl:grid-cols-4">
        {[0, 1, 2, 3].map((i) => (
          <Skeleton key={i} className="h-28" />
        ))}
      </div>
      <Skeleton className="h-72" />
    </div>
  );
}

export function AppShell() {
  const [menu, setMenu] = useState(false);
  const { pathname } = useLocation();
  const main = useRef<HTMLElement>(null);

  // new page → start at the top, and close the mobile menu
  useEffect(() => {
    main.current?.scrollTo({ top: 0 });
    setMenu(false);
  }, [pathname]);

  return (
    <div className="flex h-full bg-app">
      <a href="#main" className="sr-only focus:not-sr-only focus:fixed focus:left-3 focus:top-3 focus:z-[70] focus:rounded-control focus:bg-brand focus:px-3 focus:py-2 focus:text-white">
        Skip to content
      </a>
      <Sidebar />
      <Dialog.Root open={menu} onOpenChange={setMenu}>
        <Dialog.Portal>
          <Dialog.Overlay className="anim-overlay fixed inset-0 z-50 bg-ink/40 lg:hidden" />
          <Dialog.Content className="anim-drawer-left fixed inset-y-0 left-0 z-50 w-sidebar max-w-[85vw] lg:hidden" aria-describedby={undefined}>
            <Dialog.Title className="sr-only">Navigation</Dialog.Title>
            <SidebarContent onNavigate={() => setMenu(false)} />
          </Dialog.Content>
        </Dialog.Portal>
      </Dialog.Root>

      <div className="flex min-w-0 flex-1 flex-col">
        <Topbar onMenu={() => setMenu(true)} />
        <main id="main" ref={main} className="min-h-0 flex-1 overflow-y-auto">
          <div className="mx-auto w-full max-w-[1440px] px-4 py-6 sm:px-6 lg:px-8">
            <DemoBanner />
            <Suspense fallback={<PageFallback />}>
              <Outlet />
            </Suspense>
          </div>
        </main>
      </div>
      <AuditWatcher />
    </div>
  );
}
