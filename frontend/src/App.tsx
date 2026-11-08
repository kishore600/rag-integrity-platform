import { useQueryClient } from "@tanstack/react-query";
import { lazy, useEffect, useState } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { AppShell } from "@/components/layout/app-shell";
import { ErrorState, Skeleton } from "@/components/shared/states";
import { LinkButton } from "@/components/shared/link-button";
import { EmptyState } from "@/components/shared/states";
import { qk, useSession } from "@/hooks/queries";
import { setUnauthorizedHandler } from "@/lib/api";
import { ApiKeyGate, AuthPage, SetupRequired } from "@/pages/auth";
import { Compass } from "lucide-react";

// Each page is its own chunk: the sign-in screen does not download the charts library.
const Overview = lazy(() => import("@/pages/overview"));
const DataSources = lazy(() => import("@/pages/data-sources"));
const Reconciliation = lazy(() => import("@/pages/reconciliation"));
const Issues = lazy(() => import("@/pages/issues"));
const Documents = lazy(() => import("@/pages/documents"));
const AuditHistory = lazy(() => import("@/pages/audit-history"));
const Integrations = lazy(() => import("@/pages/integrations"));
const Alerts = lazy(() => import("@/pages/alerts"));
const Settings = lazy(() => import("@/pages/settings"));

function NotFound() {
  return (
    <EmptyState icon={Compass} title="Page not found" description="That address doesn't match anything in RAGGuard." action={<LinkButton variant="primary" to="/">Back to Overview</LinkButton>} />
  );
}

export default function App() {
  const qc = useQueryClient();
  const session = useSession();
  const [unlocked, setUnlocked] = useState(false);
  const s = session.data;

  // A 401 from any call means the session ended (or the shared key was wrong): go back to the sign-in screen.
  useEffect(() => {
    setUnauthorizedHandler(() => {
      if (s && !s.app) {
        setUnlocked(false);
        return;
      }
      qc.removeQueries({ predicate: (q) => q.queryKey[0] !== "session" });
      void qc.invalidateQueries({ queryKey: qk.session });
    });
    return () => setUnauthorizedHandler(null);
  }, [qc, s]);

  if (session.isPending) {
    return (
      <div className="flex h-full items-center justify-center bg-app" aria-busy aria-label="Loading">
        <Skeleton className="h-10 w-40" />
      </div>
    );
  }
  if (session.isError || !s) {
    return (
      <div className="flex h-full items-center justify-center bg-app">
        <ErrorState error={session.error} onRetry={() => void session.refetch()} />
      </div>
    );
  }
  if (s.app && s.setup?.required) return <SetupRequired problems={s.setup.problems} onRetry={() => void session.refetch()} />;
  if (s.app && !s.authenticated) return <AuthPage session={s} />;
  if (!s.app && s.api_key_required && !unlocked) return <ApiKeyGate onUnlock={() => setUnlocked(true)} />;

  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route index element={<Overview />} />
        <Route path="data-sources" element={<DataSources />} />
        <Route path="reconciliation" element={<Reconciliation />} />
        <Route path="issues" element={<Issues />} />
        <Route path="issues/:issueId" element={<Issues />} />
        <Route path="documents" element={<Documents />} />
        <Route path="audit-history" element={<AuditHistory />} />
        <Route path="audit-history/:runId" element={<AuditHistory />} />
        <Route path="integrations" element={<Integrations />} />
        <Route path="alerts" element={<Alerts />} />
        <Route path="settings" element={<Settings />} />
        <Route path="index.html" element={<Navigate to="/" replace />} />
        <Route path="*" element={<NotFound />} />
      </Route>
    </Routes>
  );
}
