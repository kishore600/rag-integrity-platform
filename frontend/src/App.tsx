import { useQueryClient } from "@tanstack/react-query";
import { Suspense, lazy, useEffect, useState } from "react";
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
const Landing = lazy(() => import("@/pages/landing"));
const Overview = lazy(() => import("@/pages/overview"));
const DataSources = lazy(() => import("@/pages/data-sources"));
const Reconciliation = lazy(() => import("@/pages/reconciliation"));
const Issues = lazy(() => import("@/pages/issues"));
const Isolation = lazy(() => import("@/pages/isolation"));
const Documents = lazy(() => import("@/pages/documents"));
const AuditHistory = lazy(() => import("@/pages/audit-history"));
const Integrations = lazy(() => import("@/pages/integrations"));
const Alerts = lazy(() => import("@/pages/alerts"));
const Notifications = lazy(() => import("@/pages/notifications"));
const Settings = lazy(() => import("@/pages/settings"));
// Help (the user guide and the video) is one chunk with three entry points.
const HelpHome = lazy(() => import("@/pages/help").then((m) => ({ default: m.HelpHome })));
const HelpChapter = lazy(() => import("@/pages/help").then((m) => ({ default: m.HelpChapter })));
const HelpPublicLayout = lazy(() => import("@/pages/help").then((m) => ({ default: m.HelpPublicLayout })));
const LegalPage = lazy(() => import("@/pages/legal"));
const Admin = lazy(() => import("@/pages/admin"));

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
  if (s.app && !s.authenticated) {
    // Signed out: a landing page at "/", sign-in and sign-up on their own addresses, and the sign-in form for anything else
    // (so a deep link such as /issues asks you to sign in and then lands where you were going).
    return (
      <Suspense fallback={<div className="min-h-full bg-night" aria-busy />}>
        <Routes>
          <Route index element={<Landing session={s} />} />
          {/* keys: moving between these addresses must remount the form so it opens in the right mode */}
          <Route path="login" element={<AuthPage key="login" session={s} initialMode="login" />} />
          <Route path="signup" element={<AuthPage key="signup" session={s} initialMode={s.registration_open ? "register" : "login"} />} />
          {/* the user guide and the video are public: you can read them before you sign up */}
          <Route path="help" element={<HelpPublicLayout />}>
            <Route index element={<HelpHome />} />
            <Route path=":chapter" element={<HelpChapter />} />
          </Route>
          {/* the Privacy Policy and the Terms are public too, in the same frame as the guide */}
          <Route element={<HelpPublicLayout />}>
            <Route path="privacy" element={<LegalPage doc="privacy" />} />
            <Route path="terms" element={<LegalPage doc="terms" />} />
          </Route>
          <Route path="*" element={<AuthPage key="other" session={s} initialMode="login" />} />
        </Routes>
      </Suspense>
    );
  }
  if (!s.app && s.api_key_required && !unlocked) return <ApiKeyGate onUnlock={() => setUnlocked(true)} />;

  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route index element={<Overview />} />
        <Route path="data-sources" element={<DataSources />} />
        <Route path="reconciliation" element={<Reconciliation />} />
        <Route path="issues" element={<Issues />} />
        <Route path="issues/:issueId" element={<Issues />} />
        <Route path="isolation" element={<Isolation />} />
        <Route path="documents" element={<Documents />} />
        <Route path="audit-history" element={<AuditHistory />} />
        <Route path="audit-history/:runId" element={<AuditHistory />} />
        <Route path="integrations" element={<Integrations />} />
        <Route path="alerts" element={<Alerts />} />
        <Route path="notifications" element={<Notifications />} />
        <Route path="settings" element={<Settings />} />
        <Route path="admin" element={<Admin />} />
        <Route path="help" element={<HelpHome />} />
        <Route path="help/:chapter" element={<HelpChapter />} />
        <Route path="privacy" element={<LegalPage doc="privacy" />} />
        <Route path="terms" element={<LegalPage doc="terms" />} />
        <Route path="index.html" element={<Navigate to="/" replace />} />
        {/* signed in already: the sign-in and sign-up addresses lead back into the app */}
        <Route path="login" element={<Navigate to="/" replace />} />
        <Route path="signup" element={<Navigate to="/" replace />} />
        <Route path="*" element={<NotFound />} />
      </Route>
    </Routes>
  );
}
