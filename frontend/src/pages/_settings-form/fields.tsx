import { Lock } from "lucide-react";
import { useEffect, useId, useRef, type ReactNode } from "react";
import { Button } from "@/components/ui/button";
import { Field, Input, Select, Switch, Textarea } from "@/components/ui/form";
import { cn } from "@/lib/cn";
import type { SettingsField } from "@/types/api";
import { isWide, SAVED_PLACEHOLDER } from "./model";
import { TestChecks } from "./parts";
import type { SettingsFormApi } from "./use-settings-form";

function ToggleField({ f, form }: { f: SettingsField; form: SettingsFormApi }) {
  const id = useId();
  return (
    <div className="flex items-start gap-3 rounded-control border border-line bg-app p-3 sm:col-span-2">
      <Switch id={id} checked={form.values[f.name] === true} onChange={(v) => form.setValue(f.name, v)} label={f.label} />
      <div className="min-w-0">
        <label htmlFor={id} className="block cursor-pointer text-card text-ink">{f.label}</label>
        {f.help ? <p className="mt-0.5 text-support text-ink-2">{f.help}</p> : null}
      </div>
    </div>
  );
}

/** One field, rendered from its server-side description. Nothing here knows any field by name. */
function FieldControl({ f, form }: { f: SettingsField; form: SettingsFormApi }) {
  if (f.type === "bool") return <ToggleField f={f} form={form} />;

  const value = String(form.values[f.name] ?? "");
  const error = form.errors[f.name] ?? null;
  const serverBad = form.serverField === f.name;
  const saved = f.secret && f.has_value;
  const removing = !!form.cleared[f.name];
  const set = (v: string) => form.setValue(f.name, v);

  let help: ReactNode = f.help || undefined;
  if (saved) {
    help = (
      <>
        {f.help ? <>{f.help} </> : null}
        {removing ? (
          <span>
            The saved value will be removed when you save.{" "}
            <button type="button" className="font-medium text-brand hover:underline" onClick={() => form.setCleared(f.name, false)}>Keep it</button>
          </span>
        ) : (
          <span className="inline-flex flex-wrap items-center gap-x-2">
            <span className="inline-flex items-center gap-1 font-medium text-success"><Lock className="h-3 w-3" aria-hidden /> A value is saved</span>
            {!f.required ? (
              <button type="button" className="font-medium text-brand hover:underline" onClick={() => form.setCleared(f.name, true)}>Remove saved value</button>
            ) : null}
          </span>
        )}
      </>
    );
  }

  const placeholder = removing ? "Will be removed when you save" : saved ? SAVED_PLACEHOLDER : f.placeholder || undefined;

  return (
    <Field label={f.label} required={f.required} help={help} error={error} className={cn(isWide(f) && "sm:col-span-2")}>
      {({ invalid, ...aria }) => {
        const bad = invalid || serverBad;
        if (f.type === "enum") {
          return (
            <Select {...aria} aria-invalid={bad || undefined} value={value} onChange={(e) => set(e.target.value)}>
              {f.required ? null : <option value="">Use server default</option>}
              {f.choices.map((c) => (
                <option key={c} value={c}>{c}</option>
              ))}
            </Select>
          );
        }
        if (f.type === "json") {
          return (
            <Textarea {...aria} invalid={bad} value={value} onChange={(e) => set(e.target.value)} placeholder={placeholder} rows={5} spellCheck={false} autoCapitalize="off" className="font-mono text-support" />
          );
        }
        const numeric = f.type === "int" || f.type === "float";
        return (
          <Input
            {...aria}
            invalid={bad}
            type={f.secret ? "password" : numeric ? "number" : f.type === "url" ? "url" : "text"}
            inputMode={numeric ? (f.type === "int" ? "numeric" : "decimal") : f.type === "url" || f.type === "pgurl" ? "url" : undefined}
            step={f.type === "float" ? "any" : f.type === "int" ? 1 : undefined}
            autoComplete="off"
            autoCapitalize="off"
            spellCheck={false}
            disabled={removing}
            value={value}
            onChange={(e) => set(e.target.value)}
            placeholder={placeholder}
          />
        );
      }}
    </Field>
  );
}

/** Every field of the group. After a blocked submit, focus moves to the first field with a problem. */
export function SettingsFields({ form }: { form: SettingsFormApi }) {
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (form.focusTick > 0) box.current?.querySelector<HTMLElement>('[aria-invalid="true"]')?.focus();
  }, [form.focusTick]);
  return (
    <div ref={box} className="grid grid-cols-1 gap-4 sm:grid-cols-2">
      {form.group.fields.map((f) => (
        <FieldControl key={f.name} f={f} form={form} />
      ))}
    </div>
  );
}

/** The server's validation message (HTTP 400/422) and the result of the last test run. */
export function SettingsFeedback({ form }: { form: SettingsFormApi }) {
  const box = useRef<HTMLDivElement>(null);
  // The buttons live in a footer: bring the outcome into view so a click never appears to do nothing.
  useEffect(() => {
    if (form.serverError || form.result) box.current?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [form.serverError, form.result]);
  if (!form.serverError && !form.result) return null;
  return (
    <div ref={box} className="space-y-3">
      {form.serverError ? <p className="break-words rounded-control bg-critical-bg px-3 py-2 text-support text-critical" role="alert">{form.serverError}</p> : null}
      {form.result ? <TestChecks result={form.result} /> : null}
    </div>
  );
}

/** Test (optional), Cancel (optional) and Save. Save is tied to the form by id, so the same buttons work in a modal footer. */
export function SettingsActions({ form, testLabel = "Test connection", onCancel, saveLabel = "Save" }: { form: SettingsFormApi; testLabel?: string | null; onCancel?: () => void; saveLabel?: string }) {
  return (
    <>
      {testLabel !== null ? (
        <Button variant="secondary" onClick={form.runTest} loading={form.testing} disabled={form.saving}>{testLabel}</Button>
      ) : null}
      {onCancel ? <Button variant="secondary" onClick={onCancel} disabled={form.saving}>Cancel</Button> : null}
      <Button type="submit" form={form.formId} variant="primary" loading={form.saving} disabled={!form.dirty || form.testing}>{saveLabel}</Button>
    </>
  );
}
