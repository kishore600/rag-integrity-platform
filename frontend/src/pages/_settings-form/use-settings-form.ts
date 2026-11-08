import { useCallback, useEffect, useId, useMemo, useState, type FormEvent } from "react";
import { toast } from "sonner";
import { useSaveSettings, useTestSettings } from "@/hooks/queries";
import { errorMessage } from "@/lib/api";
import type { SettingsGroup, SettingsView, TestResult } from "@/types/api";
import { buildPayload, fieldForServerError, hasChanges, initialValues, validate, type Cleared, type Values, type FormValue } from "./model";

export interface SettingsFormApi {
  group: SettingsGroup;
  formId: string;
  values: Values;
  cleared: Cleared;
  /** Inline messages per field (client validation after the first attempt, plus the field a server error is about). */
  errors: Record<string, string>;
  serverField: string | null;
  serverError: string | null;
  result: TestResult | null;
  dirty: boolean;
  saving: boolean;
  testing: boolean;
  /** Increments when a submit or test was blocked by validation, so the fields can move focus to the first problem. */
  focusTick: number;
  setValue: (name: string, value: FormValue) => void;
  setCleared: (name: string, cleared: boolean) => void;
  submit: (e?: FormEvent) => void;
  runTest: () => void;
  reset: (to?: SettingsGroup) => void;
}

/**
 * All the state of one settings group's form. Both the inline card form and the modal form are built on it.
 * Save and Test send only what the user changed; the server merges that over what is stored.
 */
export function useSettingsForm(group: SettingsGroup, opts: { onSaved?: (view: SettingsView) => void } = {}): SettingsFormApi {
  const formId = useId();
  const [base, setBase] = useState(group);
  const baseValues = useMemo(() => initialValues(base), [base]);
  const [values, setValues] = useState<Values>(() => initialValues(group));
  const [cleared, setClearedState] = useState<Cleared>({});
  const [attempted, setAttempted] = useState(false);
  const [serverError, setServerError] = useState<string | null>(null);
  const [serverField, setServerField] = useState<string | null>(null);
  const [result, setResult] = useState<TestResult | null>(null);
  const [focusTick, setFocusTick] = useState(0);
  const save = useSaveSettings();
  const test = useTestSettings();

  const dirty = hasChanges(group, baseValues, values, cleared);
  const problems = useMemo(() => validate(group, baseValues, values, cleared), [group, baseValues, values, cleared]);

  const rebase = useCallback((to: SettingsGroup) => {
    setBase(to);
    setValues(initialValues(to));
    setClearedState({});
    setAttempted(false);
    setServerError(null);
    setServerField(null);
    setResult(null);
  }, []);

  // The saved settings changed underneath an untouched form (another tab, a refresh): show the new values.
  useEffect(() => {
    if (group !== base && !hasChanges(base, baseValues, values, cleared)) {
      setBase(group);
      setValues(initialValues(group));
    }
  }, [group, base, baseValues, values, cleared]);

  const setValue = useCallback((name: string, value: FormValue) => {
    setValues((v) => ({ ...v, [name]: value }));
    setResult(null);
    setServerField((f) => (f === name ? null : f));
  }, []);

  const setCleared = useCallback((name: string, on: boolean) => {
    setClearedState((c) => ({ ...c, [name]: on }));
    setValues((v) => ({ ...v, [name]: "" }));
    setResult(null);
  }, []);

  const blocked = (): boolean => {
    setServerError(null);
    setServerField(null);
    if (Object.keys(problems).length > 0) {
      setAttempted(true);
      setFocusTick((t) => t + 1);
      return true;
    }
    return false;
  };

  const submit = (e?: FormEvent) => {
    e?.preventDefault();
    if (save.isPending || blocked() || !dirty) return;
    save.mutate(
      { kind: group.kind, values: buildPayload(group, baseValues, values, cleared) },
      {
        onSuccess: (view) => {
          const saved = view.kinds.find((k) => k.kind === group.kind);
          if (saved) rebase(saved);
          toast.success(`${group.title} saved`);
          opts.onSaved?.(view);
        },
        onError: (err) => {
          const msg = errorMessage(err);
          setServerError(msg);
          setServerField(fieldForServerError(group, msg));
        },
      },
    );
  };

  const runTest = () => {
    if (test.isPending || blocked()) return;
    const payload = buildPayload(group, baseValues, values, cleared);
    setResult(null);
    if (!group.configured && Object.keys(payload).length === 0) {
      setServerError("Nothing to check yet. Fill in a field first.");
      return;
    }
    test.mutate(
      { kind: group.kind, values: payload },
      {
        onSuccess: (r) => setResult(r),
        onError: (err) => {
          const msg = errorMessage(err);
          setServerError(msg);
          setServerField(fieldForServerError(group, msg));
        },
      },
    );
  };

  return {
    group,
    formId,
    values,
    cleared,
    errors: attempted ? problems : {},
    serverField,
    serverError,
    result,
    dirty,
    saving: save.isPending,
    testing: test.isPending,
    focusTick,
    setValue,
    setCleared,
    submit,
    runTest,
    reset: (to) => rebase(to ?? group),
  };
}
