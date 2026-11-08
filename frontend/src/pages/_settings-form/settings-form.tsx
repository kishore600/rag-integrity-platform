import { useEffect, type ReactNode } from "react";
import { Modal } from "@/components/ui/overlays";
import { cn } from "@/lib/cn";
import type { SettingsGroup, SettingsView } from "@/types/api";
import { SettingsActions, SettingsFeedback, SettingsFields } from "./fields";
import { SavedStatus } from "./parts";
import { useSettingsForm } from "./use-settings-form";

interface CommonProps {
  group: SettingsGroup;
  /** Label of the check button. `null` hides it (groups that connect to nothing, such as the pipeline target). */
  testLabel?: string | null;
  /** One sentence under the form saying what the check does. */
  testNote?: ReactNode;
  onSaved?: (view: SettingsView) => void;
}

/** One settings group as an inline form (put it in a Card). Fields come from the server's description of the group. */
export function SettingsForm({ group, testLabel, testNote, onSaved, className }: CommonProps & { className?: string }) {
  const form = useSettingsForm(group, { onSaved });
  return (
    <form id={form.formId} onSubmit={form.submit} noValidate className={cn("space-y-4", className)} aria-label={group.title}>
      <SettingsFields form={form} />
      <SettingsFeedback form={form} />
      <div className="flex flex-wrap items-center justify-between gap-3 border-t border-line pt-4">
        <div className="min-w-0 space-y-0.5">
          <SavedStatus group={group} showTest={testLabel === undefined} />
          {testLabel !== null && testNote ? <p className="text-support text-ink-2">{testNote}</p> : null}
          {!form.dirty ? <p className="text-support text-ink-3">No unsaved changes.</p> : null}
        </div>
        <div className="flex flex-wrap gap-2">
          <SettingsActions form={form} testLabel={testLabel} />
        </div>
      </div>
    </form>
  );
}

/** The same form inside a dialog. It starts from the saved values every time it opens, and closes after a successful save. */
export function SettingsModal({
  group,
  open,
  onOpenChange,
  title,
  description,
  testLabel,
  testNote,
  onSaved,
}: CommonProps & { open: boolean; onOpenChange: (open: boolean) => void; title?: string; description?: ReactNode }) {
  const form = useSettingsForm(group, {
    onSaved: (view) => {
      onOpenChange(false);
      onSaved?.(view);
    },
  });
  const { reset } = form;
  useEffect(() => {
    if (open) reset();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  return (
    <Modal
      open={open}
      onOpenChange={(o) => {
        if (!form.saving) onOpenChange(o);
      }}
      title={title ?? group.title}
      description={description ?? group.description}
      size="lg"
      footer={<SettingsActions form={form} testLabel={testLabel} onCancel={() => onOpenChange(false)} />}
    >
      <form id={form.formId} onSubmit={form.submit} noValidate className="space-y-4" aria-label={group.title}>
        <SavedStatus group={group} showTest={testLabel === undefined} />
        <SettingsFields form={form} />
        <SettingsFeedback form={form} />
        {testLabel !== null && testNote ? <p className="text-support text-ink-2">{testNote}</p> : null}
      </form>
    </Modal>
  );
}
