import { useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, CheckCircle2, KeyRound, ServerCrash } from "lucide-react";
import { useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { Logo } from "@/components/brand/logo";
import { Button } from "@/components/ui/button";
import { Field, Input } from "@/components/ui/form";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/menus";
import { ApiError, errorMessage, get, post, setApiKey } from "@/lib/api";
import { qk } from "@/hooks/queries";
import type { Session } from "@/types/api";

const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const MIN_PASSWORD = 10;

function Frame({ children, home }: { children: React.ReactNode; /** show a way back to the landing page (signed-out visitors only) */ home?: boolean }) {
  return (
    <div className="grid min-h-full lg:grid-cols-[minmax(0,1fr)_minmax(420px,520px)]">
      <div className="relative hidden flex-col justify-between overflow-hidden bg-night p-12 text-sidebar-text lg:flex">
        <div className="pointer-events-none absolute inset-0 bg-dots opacity-60 [mask-image:radial-gradient(ellipse_at_top_left,black_25%,transparent_75%)]" aria-hidden />
        <div className="pointer-events-none absolute -left-24 -top-24 h-[360px] w-[360px] rounded-full bg-brand/30 blur-[110px]" aria-hidden />
        <div className="relative">
          <Logo size={38} />
        </div>
        <div className="relative max-w-lg">
          <h2 className="text-[34px] font-semibold leading-tight tracking-tight text-white">Know when your RAG index is wrong, before your users do.</h2>
          <p className="mt-4 text-section font-normal text-sidebar-text">
            RAGGuard compares what you meant to index (your documents) with what is actually searchable (your vector store) and tells you exactly what drifted.
          </p>
          <ul className="mt-8 space-y-3 text-body">
            {[
              "Finds missing, stale, partial and orphaned embeddings",
              "Shows the evidence behind every finding, with a safe fix",
              "Verifies repairs by re-checking the real index",
            ].map((t) => (
              <li key={t} className="flex items-start gap-2.5 text-sidebar-icon">
                <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-sidebar-icon" aria-hidden /> {t}
              </li>
            ))}
          </ul>
        </div>
        <p className="relative text-support text-sidebar-text/70">Your connection secrets are encrypted at rest and never shown again after saving.</p>
      </div>
      <div className="flex flex-col items-center justify-center bg-workspace px-6 py-10">
        <div className="w-full max-w-sm">
          <div className="mb-8 flex items-center justify-between lg:mb-6 lg:justify-end">
            <Link to="/" className="rounded-control lg:hidden" aria-label="RAGGuard home">
              <Logo tone="light" size={32} />
            </Link>
            {home ? (
              <Link to="/" className="inline-flex items-center gap-1.5 text-support font-medium text-ink-2 hover:text-ink">
                <ArrowLeft className="h-3.5 w-3.5" aria-hidden /> Back to home
              </Link>
            ) : null}
          </div>
          {children}
        </div>
      </div>
    </div>
  );
}

export function AuthPage({ session, initialMode = "login" }: { session: Session; initialMode?: "login" | "register" }) {
  const qc = useQueryClient();
  const canRegister = !!session.registration_open;
  const [mode, setMode] = useState<"login" | "register">(canRegister ? initialMode : "login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [errors, setErrors] = useState<{ email?: string; password?: string; form?: string }>({});

  async function submit(e: FormEvent) {
    e.preventDefault();
    const next: typeof errors = {};
    if (!EMAIL.test(email.trim())) next.email = "Enter a valid email address.";
    if (!password) next.password = "Enter your password.";
    else if (mode === "register" && password.length < MIN_PASSWORD) next.password = `Use at least ${MIN_PASSWORD} characters.`;
    setErrors(next);
    if (next.email || next.password) return;
    setBusy(true);
    try {
      await post(mode === "login" ? "/api/auth/login" : "/api/auth/register", { email: email.trim(), password });
      await qc.invalidateQueries({ queryKey: qk.session });
    } catch (err) {
      setErrors({ form: errorMessage(err) });
    } finally {
      setBusy(false);
    }
  }

  return (
    <Frame home>
      <h1 className="text-page">{mode === "login" ? "Welcome back" : "Create your workspace"}</h1>
      <p className="mt-1 text-body text-ink-2">{mode === "login" ? "Sign in to see the health of your RAG index." : "Each account gets a private workspace with its own connections."}</p>

      {canRegister ? (
        <Tabs value={mode} onValueChange={(v) => { setMode(v as "login" | "register"); setErrors({}); }} className="mt-6">
          <TabsList>
            <TabsTrigger value="login">Sign in</TabsTrigger>
            <TabsTrigger value="register">Create account</TabsTrigger>
          </TabsList>
        </Tabs>
      ) : null}

      <form onSubmit={submit} className="mt-6 space-y-4" noValidate>
        <Field label="Email" error={errors.email}>
          {(p) => <Input {...p} type="email" autoComplete="email" autoFocus value={email} onChange={(e) => setEmail(e.target.value)} placeholder="you@company.com" />}
        </Field>
        <Field label="Password" error={errors.password} help={mode === "register" ? `At least ${MIN_PASSWORD} characters.` : undefined}>
          {(p) => <Input {...p} type="password" autoComplete={mode === "login" ? "current-password" : "new-password"} value={password} onChange={(e) => setPassword(e.target.value)} />}
        </Field>
        {errors.form ? (
          <p className="rounded-control bg-critical-bg px-3 py-2 text-support text-critical" role="alert">{errors.form}</p>
        ) : null}
        <Button type="submit" variant="primary" size="lg" className="w-full" loading={busy}>
          {mode === "login" ? "Sign in" : "Create account"}
        </Button>
      </form>
      {!canRegister ? <p className="mt-4 text-support text-ink-2">New sign-ups are closed on this server.</p> : null}
    </Frame>
  );
}

export function SetupRequired({ problems, onRetry }: { problems?: string[]; onRetry: () => void }) {
  return (
    <div className="flex min-h-full items-center justify-center bg-app px-6 py-12">
      <div className="w-full max-w-lg rounded-card border border-line bg-workspace p-8 shadow-card">
        <div className="mb-4 flex h-11 w-11 items-center justify-center rounded-full bg-warning-bg text-warning">
          <ServerCrash className="h-5 w-5" aria-hidden />
        </div>
        <h1 className="text-page">This server isn't fully set up yet</h1>
        <p className="mt-2 text-body text-ink-2">The operator needs to finish the deployment configuration before accounts can be used.</p>
        {problems?.length ? (
          <ul className="mt-4 list-disc space-y-1 pl-5 text-body text-ink">
            {problems.map((p) => (
              <li key={p}>{p}</li>
            ))}
          </ul>
        ) : null}
        <Button variant="secondary" className="mt-6" onClick={onRetry}>Check again</Button>
      </div>
    </div>
  );
}

/** Single-user servers protected by a shared RAGI_API_KEY. The key lives in memory only. */
export function ApiKeyGate({ onUnlock }: { onUnlock: () => void }) {
  const [key, setKey] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!key.trim()) {
      setError("Enter the API key.");
      return;
    }
    setBusy(true);
    setError(null);
    setApiKey(key.trim());
    try {
      await get("/api/overview");
      onUnlock();
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        setApiKey("");
        setError("That key was not accepted.");
      } else {
        onUnlock(); // reachable and authorised; any other failure is shown by the page itself
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <Frame>
      <div className="mb-4 flex h-11 w-11 items-center justify-center rounded-full bg-brand-light text-brand">
        <KeyRound className="h-5 w-5" aria-hidden />
      </div>
      <h1 className="text-page">API key required</h1>
      <p className="mt-1 text-body text-ink-2">This server is protected. Enter its API key to continue. It is kept in memory only and is forgotten when you close the tab.</p>
      <form onSubmit={submit} className="mt-6 space-y-4" noValidate>
        <Field label="API key" error={error}>
          {(p) => <Input {...p} type="password" autoComplete="off" autoFocus value={key} onChange={(e) => setKey(e.target.value)} />}
        </Field>
        <Button type="submit" variant="primary" size="lg" className="w-full" loading={busy}>Continue</Button>
      </form>
    </Frame>
  );
}
