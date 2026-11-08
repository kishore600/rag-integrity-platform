import { useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Field, Input } from "@/components/ui/form";
import { ConfirmDialog } from "@/components/ui/overlays";
import { KeyValue } from "@/components/shared/page";
import { useChangePassword } from "@/hooks/queries";
import { errorMessage, post } from "@/lib/api";
import type { Session } from "@/types/api";
import { EnvNote } from "../_settings-form";

const MIN_PASSWORD = 10;
const MAX_PASSWORD = 128;

const MODE_LABEL: Record<string, string> = { app: "App (multi-user)", live: "Live (single-user)", demo: "Demo (single-user)" };

function PasswordCard() {
  const change = useChangePassword();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [errors, setErrors] = useState<{ current?: string; next?: string; confirm?: string; form?: string }>({});

  function submit(e: FormEvent) {
    e.preventDefault();
    const found: typeof errors = {};
    if (!current) found.current = "Enter your current password.";
    if (next.length < MIN_PASSWORD) found.next = `Use at least ${MIN_PASSWORD} characters.`;
    else if (next.length > MAX_PASSWORD) found.next = `Use at most ${MAX_PASSWORD} characters.`;
    else if (current && next === current) found.next = "Choose a password that is different from the current one.";
    if (confirm !== next) found.confirm = "The two passwords do not match.";
    setErrors(found);
    if (found.current || found.next || found.confirm) return;
    change.mutate(
      { current_password: current, new_password: next },
      {
        onSuccess: () => {
          setCurrent("");
          setNext("");
          setConfirm("");
          toast.success("Password updated", { description: "Your other signed-in sessions were signed out." });
        },
        onError: (err) => {
          const msg = errorMessage(err);
          setErrors(/current password/i.test(msg) ? { current: msg } : { form: msg });
        },
      },
    );
  }

  return (
    <Card>
      <CardHeader title="Change password" description={`Use ${MIN_PASSWORD} to ${MAX_PASSWORD} characters. Avoid common passwords and anything that contains your email name.`} />
      <CardBody>
        <form onSubmit={submit} noValidate className="max-w-md space-y-4" aria-label="Change password">
          <Field label="Current password" required error={errors.current}>
            {(p) => <Input {...p} type="password" autoComplete="current-password" value={current} onChange={(e) => setCurrent(e.target.value)} />}
          </Field>
          <Field label="New password" required error={errors.next} help={`At least ${MIN_PASSWORD} characters.`}>
            {(p) => <Input {...p} type="password" autoComplete="new-password" value={next} onChange={(e) => setNext(e.target.value)} />}
          </Field>
          <Field label="Confirm new password" required error={errors.confirm}>
            {(p) => <Input {...p} type="password" autoComplete="new-password" value={confirm} onChange={(e) => setConfirm(e.target.value)} />}
          </Field>
          {errors.form ? <p className="rounded-control bg-critical-bg px-3 py-2 text-support text-critical" role="alert">{errors.form}</p> : null}
          <Button type="submit" variant="primary" loading={change.isPending}>Update password</Button>
        </form>
      </CardBody>
    </Card>
  );
}

function DemoResetCard() {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  return (
    <Card>
      <CardHeader title="Demo data" description="This server runs on synthetic data so you can explore the product." />
      <CardBody>
        <Button variant="danger-outline" onClick={() => setOpen(true)}>Reset demo data</Button>
      </CardBody>
      <ConfirmDialog
        open={open}
        onOpenChange={setOpen}
        title="Reset demo data?"
        description="This regenerates the synthetic demo data and clears the current results."
        confirmLabel="Reset demo data"
        destructive
        onConfirm={async () => {
          await post("/api/demo/reset");
          void qc.invalidateQueries();
          toast.success("Demo data reset", { description: "New synthetic data is loading." });
        }}
      />
    </Card>
  );
}

export function GeneralTab({ session }: { session: Session }) {
  const modeLabel = MODE_LABEL[session.mode] ?? session.mode;
  return (
    <div className="space-y-6">
      {session.app ? (
        <Card>
          <CardHeader title="Workspace" description="Your connections, issues and audit history live in one private workspace." />
          <CardBody className="space-y-4">
            <KeyValue
              items={[
                { label: "Workspace name", value: session.workspace?.name ?? "Workspace" },
                { label: "Account email", value: session.user?.email ?? "Unknown" },
                { label: "Server mode", value: modeLabel },
                { label: "Version", value: session.version },
              ]}
            />
            <p className="text-support text-ink-2">Renaming the workspace is not available yet.</p>
          </CardBody>
        </Card>
      ) : (
        <Card>
          <CardHeader title="Server" description="This RAGGuard server runs for one team without sign-in accounts." />
          <CardBody className="space-y-4">
            <KeyValue
              items={[
                { label: "Server mode", value: modeLabel },
                { label: "Version", value: session.version },
              ]}
            />
            <EnvNote />
          </CardBody>
        </Card>
      )}

      {session.app ? <PasswordCard /> : null}
      {session.demo ? <DemoResetCard /> : null}
    </div>
  );
}
