/**
 * Modal, Drawer and ConfirmDialog built on Radix Dialog: focus is trapped, Escape closes, focus returns to the trigger,
 * and the page behind is inert for assistive technology.
 */
import * as Dialog from "@radix-ui/react-dialog";
import { X } from "lucide-react";
import { useState, type ReactNode } from "react";
import { cn } from "@/lib/cn";
import { errorMessage } from "@/lib/api";
import { Button } from "./button";

const overlay = "anim-overlay fixed inset-0 z-50 bg-ink/40 backdrop-blur-[1px]";

interface CommonProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: ReactNode;
  description?: ReactNode;
  children?: ReactNode;
}

const modalWidths = { sm: "max-w-md", md: "max-w-xl", lg: "max-w-3xl" } as const;

export function Modal({ open, onOpenChange, title, description, children, footer, size = "md" }: CommonProps & { footer?: ReactNode; size?: keyof typeof modalWidths }) {
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className={overlay} />
        <Dialog.Content
          className={cn("anim-modal fixed left-1/2 top-1/2 z-50 flex max-h-[88vh] w-[calc(100%-32px)] -translate-x-1/2 -translate-y-1/2 flex-col rounded-card border border-line bg-workspace shadow-pop", modalWidths[size])}
        >
          <div className="flex items-start justify-between gap-4 border-b border-line px-5 py-4">
            <div className="min-w-0">
              <Dialog.Title className="text-section text-ink">{title}</Dialog.Title>
              {description ? <Dialog.Description className="mt-0.5 text-support text-ink-2">{description}</Dialog.Description> : <Dialog.Description className="sr-only">{typeof title === "string" ? title : "Dialog"}</Dialog.Description>}
            </div>
            <Dialog.Close asChild>
              <Button variant="ghost" size="icon-sm" aria-label="Close"><X className="h-4 w-4" /></Button>
            </Dialog.Close>
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">{children}</div>
          {footer ? <div className="flex flex-wrap items-center justify-end gap-2 border-t border-line bg-app px-5 py-3">{footer}</div> : null}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

const drawerWidths = { md: "sm:w-[480px]", lg: "sm:w-[640px]", xl: "sm:w-[760px]" } as const;

/** A right-hand detail panel (issues, documents). `actions` render in the header next to the close button. */
export function Drawer({ open, onOpenChange, title, description, children, actions, footer, width = "lg" }: CommonProps & { actions?: ReactNode; footer?: ReactNode; width?: keyof typeof drawerWidths }) {
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className={overlay} />
        <Dialog.Content className={cn("anim-drawer fixed inset-y-0 right-0 z-50 flex w-full max-w-full flex-col border-l border-line bg-workspace shadow-pop", drawerWidths[width])}>
          <div className="flex items-start justify-between gap-3 border-b border-line px-5 py-4">
            <div className="min-w-0">
              <Dialog.Title className="truncate text-section text-ink">{title}</Dialog.Title>
              {description ? <Dialog.Description asChild><div className="mt-1 text-support text-ink-2">{description}</div></Dialog.Description> : <Dialog.Description className="sr-only">Details</Dialog.Description>}
            </div>
            <div className="flex shrink-0 items-center gap-1">
              {actions}
              <Dialog.Close asChild>
                <Button variant="ghost" size="icon-sm" aria-label="Close panel"><X className="h-4 w-4" /></Button>
              </Dialog.Close>
            </div>
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto">{children}</div>
          {footer ? <div className="flex flex-wrap items-center justify-end gap-2 border-t border-line bg-app px-5 py-3">{footer}</div> : null}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

/** Confirm a consequential action. The handler may be async: the button shows progress and an error stays in the dialog. */
export function ConfirmDialog({
  open,
  onOpenChange,
  title,
  description,
  confirmLabel = "Confirm",
  destructive,
  onConfirm,
  children,
}: CommonProps & { confirmLabel?: string; destructive?: boolean; onConfirm: () => Promise<unknown> | unknown }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function run() {
    setBusy(true);
    setError(null);
    try {
      await onConfirm();
      onOpenChange(false);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal
      open={open}
      onOpenChange={(o) => {
        if (!busy) {
          setError(null);
          onOpenChange(o);
        }
      }}
      title={title}
      description={description}
      size="sm"
      footer={
        <>
          <Button variant="secondary" onClick={() => onOpenChange(false)} disabled={busy}>Cancel</Button>
          <Button variant={destructive ? "danger" : "primary"} onClick={run} loading={busy}>{confirmLabel}</Button>
        </>
      }
    >
      {children}
      {error ? <p className="mt-3 rounded-control bg-critical-bg px-3 py-2 text-support text-critical" role="alert">{error}</p> : null}
    </Modal>
  );
}
