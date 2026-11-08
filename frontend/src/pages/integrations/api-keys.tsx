import * as Dialog from "@radix-ui/react-dialog";
import type { ColumnDef } from "@tanstack/react-table";
import { KeyRound, Plus } from "lucide-react";
import { useEffect, useMemo, useState, type FormEvent } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card, CardHeader } from "@/components/ui/card";
import { Field, Input } from "@/components/ui/form";
import { ConfirmDialog, Modal } from "@/components/ui/overlays";
import { CopyButton } from "@/components/shared/copy-button";
import { DataTable } from "@/components/shared/data-table";
import { Mono } from "@/components/shared/page";
import { EmptyState } from "@/components/shared/states";
import { useApiKeys, useCreateApiKey, useRevokeApiKey } from "@/hooks/queries";
import { errorMessage } from "@/lib/api";
import { formatDateTime, timeAgo } from "@/lib/format";
import type { ApiKey, CreatedApiKey } from "@/types/api";
import { CodeBlock, QueryGate } from "../_settings-form";

const MAX_NAME = 80;

function CreateKeyModal({ open, onOpenChange, onCreated }: { open: boolean; onOpenChange: (o: boolean) => void; onCreated: (k: CreatedApiKey) => void }) {
  const [name, setName] = useState("");
  const [fieldError, setFieldError] = useState<string | null>(null);
  const [serverError, setServerError] = useState<string | null>(null);
  const create = useCreateApiKey();

  useEffect(() => {
    if (open) {
      setName("");
      setFieldError(null);
      setServerError(null);
    }
  }, [open]);

  function submit(e: FormEvent) {
    e.preventDefault();
    const clean = name.trim();
    if (!clean) {
      setFieldError("Enter a name for the key.");
      return;
    }
    if (clean.length > MAX_NAME) {
      setFieldError(`Use at most ${MAX_NAME} characters.`);
      return;
    }
    setFieldError(null);
    setServerError(null);
    create.mutate(clean, {
      onSuccess: (res) => {
        onOpenChange(false);
        onCreated(res);
      },
      onError: (err) => setServerError(errorMessage(err)),
    });
  }

  return (
    <Modal
      open={open}
      onOpenChange={(o) => {
        if (!create.isPending) onOpenChange(o);
      }}
      title="Create API key"
      description="Name it after what will use it, such as a CI job or a nightly script."
      size="sm"
      footer={
        <>
          <Button variant="secondary" onClick={() => onOpenChange(false)} disabled={create.isPending}>Cancel</Button>
          <Button type="submit" form="create-api-key-form" variant="primary" loading={create.isPending}>Create key</Button>
        </>
      }
    >
      <form id="create-api-key-form" onSubmit={submit} noValidate className="space-y-4">
        <Field label="Name" required error={fieldError} help={`Up to ${MAX_NAME} characters.`}>
          {(p) => <Input {...p} autoFocus autoComplete="off" maxLength={MAX_NAME} value={name} onChange={(e) => setName(e.target.value)} placeholder="Nightly audit job" />}
        </Field>
        {serverError ? <p className="rounded-control bg-critical-bg px-3 py-2 text-support text-critical" role="alert">{serverError}</p> : null}
      </form>
    </Modal>
  );
}

/** The only moment the token exists in the browser. It cannot be dismissed by Escape, a click outside or a close icon: only by confirming the copy. */
function TokenDialog({ created, onDone }: { created: CreatedApiKey | null; onDone: () => void }) {
  return (
    <Dialog.Root open={!!created}>
      <Dialog.Portal>
        <Dialog.Overlay className="anim-overlay fixed inset-0 z-50 bg-ink/40 backdrop-blur-[1px]" />
        <Dialog.Content
          onEscapeKeyDown={(e) => e.preventDefault()}
          onPointerDownOutside={(e) => e.preventDefault()}
          onInteractOutside={(e) => e.preventDefault()}
          className="anim-modal fixed left-1/2 top-1/2 z-50 flex max-h-[88vh] w-[calc(100%-32px)] max-w-xl -translate-x-1/2 -translate-y-1/2 flex-col rounded-card border border-line bg-workspace shadow-pop"
        >
          <div className="border-b border-line px-5 py-4">
            <Dialog.Title className="text-section text-ink">Your new API key</Dialog.Title>
            <Dialog.Description className="mt-0.5 text-support text-ink-2">{created?.note ?? "Copy the token now: it is shown only once."}</Dialog.Description>
          </div>
          <div className="min-h-0 flex-1 space-y-4 overflow-y-auto px-5 py-4">
            {created ? (
              <div className="rounded-card border border-brand/30 bg-brand-light p-4">
                <p className="text-support text-ink-2">Token for <span className="font-medium text-ink">{created.key.name}</span></p>
                <code className="mt-2 block select-all break-all rounded-control border border-line bg-workspace px-3 py-2 font-mono text-body text-ink">{created.token}</code>
                <div className="mt-3">
                  <CopyButton text={created.token} label="Copy token" size="md" />
                </div>
              </div>
            ) : null}
            <p className="text-support text-ink-2">RAGGuard stores only a hash of this token, so it cannot show it again. If you lose it, revoke the key and create a new one.</p>
          </div>
          <div className="flex justify-end border-t border-line bg-app px-5 py-3">
            <Button variant="primary" onClick={onDone}>I&apos;ve copied it</Button>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

export function ApiKeysSection() {
  const keys = useApiKeys();
  const revoke = useRevokeApiKey();
  const [createOpen, setCreateOpen] = useState(false);
  const [created, setCreated] = useState<CreatedApiKey | null>(null);
  const [revoking, setRevoking] = useState<ApiKey | null>(null);
  const origin = window.location.origin;

  const columns = useMemo<ColumnDef<ApiKey>[]>(
    () => [
      { accessorKey: "name", header: "Name", cell: (c) => <span className="font-medium">{c.row.original.name}</span> },
      { accessorKey: "prefix", header: "Key", enableSorting: false, cell: (c) => <Mono>{c.row.original.prefix}…</Mono> },
      {
        accessorKey: "created_at",
        header: "Created",
        cell: (c) => <span title={formatDateTime(c.row.original.created_at)}>{timeAgo(c.row.original.created_at)}</span>,
      },
      {
        id: "last_used_at",
        header: "Last used",
        accessorFn: (k) => k.last_used_at ?? "",
        cell: (c) => (c.row.original.last_used_at ? <span title={formatDateTime(c.row.original.last_used_at)}>{timeAgo(c.row.original.last_used_at)}</span> : <span className="text-ink-2">Never</span>),
      },
      {
        id: "actions",
        header: () => <span className="sr-only">Actions</span>,
        enableSorting: false,
        meta: { className: "w-28 text-right" },
        cell: (c) => (
          <Button variant="danger-outline" size="sm" onClick={() => setRevoking(c.row.original)} aria-label={`Revoke API key ${c.row.original.name}`}>Revoke</Button>
        ),
      },
    ],
    [],
  );

  return (
    <Card>
      <CardHeader
        title="API keys"
        description="For CI jobs, scripts and other systems that call RAGGuard on your behalf."
        actions={
          <Button variant="primary" onClick={() => setCreateOpen(true)}>
            <Plus className="h-4 w-4" aria-hidden /> Create API key
          </Button>
        }
      />
      <QueryGate query={keys} compact>
        {(rows) => (
          <DataTable
            label="API keys"
            data={rows}
            columns={columns}
            getRowId={(k) => k.id}
            loading={false}
            initialSort={[{ id: "created_at", desc: true }]}
            empty={
              <EmptyState
                compact
                icon={KeyRound}
                title="No API keys yet"
                description="Create a key to call RAGGuard from a CI job or a script."
                action={<Button variant="primary" onClick={() => setCreateOpen(true)}>Create API key</Button>}
              />
            }
          />
        )}
      </QueryGate>

      <div className="space-y-3 border-t border-line px-5 py-4">
        <div>
          <h3 className="text-card text-ink">How to use a key</h3>
          <p className="mt-0.5 text-support text-ink-2">
            Send it in the Authorization header. A key works only inside this workspace: it can read and write data (run audits, read results) but it cannot read settings, create keys or change passwords.
          </p>
        </div>
        <CodeBlock label="Example request" code={`curl -H "Authorization: Bearer <your key>" ${origin}/api/overview`} />
      </div>

      <CreateKeyModal open={createOpen} onOpenChange={setCreateOpen} onCreated={setCreated} />
      <TokenDialog created={created} onDone={() => setCreated(null)} />
      <ConfirmDialog
        open={!!revoking}
        onOpenChange={(o) => {
          if (!o) setRevoking(null);
        }}
        title="Revoke this API key?"
        description={revoking ? `${revoking.name} (${revoking.prefix}…)` : undefined}
        confirmLabel="Revoke key"
        destructive
        onConfirm={async () => {
          if (!revoking) return;
          await revoke.mutateAsync(revoking.id);
          toast.success("API key revoked");
        }}
      >
        <p className="text-body text-ink-2">Anyone using this key loses access immediately. This cannot be undone.</p>
      </ConfirmDialog>
    </Card>
  );
}
