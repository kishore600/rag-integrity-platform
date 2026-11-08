/**
 * Pure helpers behind the settings forms: initial values, "what did the user change", and client-side validation.
 * They mirror `apply_values` in src/ragintegrity/workspaces.py:
 *   - a secret that is omitted keeps its stored value, "" clears it (so a blank secret box must never be sent);
 *   - a normal field set to "" is cleared back to the server default;
 *   - only fields that changed are sent, so a save never rewrites what the user did not touch.
 */
import type { SettingsField, SettingsGroup, TestResult } from "@/types/api";

export type FormValue = string | boolean;
export type Values = Record<string, FormValue>;
/** Secret fields the user chose to remove (only allowed for optional ones). */
export type Cleared = Record<string, boolean>;

export const SAVED_PLACEHOLDER = "Saved. Leave blank to keep it.";

const CSV_ITEM = /^[A-Za-z0-9_.-]{1,255}$/;

function prettyJson(raw: string): string {
  try {
    return JSON.stringify(JSON.parse(raw), null, 2);
  } catch {
    return raw;
  }
}

function normalizedJson(raw: string): string {
  try {
    return JSON.stringify(JSON.parse(raw));
  } catch {
    return raw.trim();
  }
}

export function initialValue(f: SettingsField): FormValue {
  if (f.secret) return "";
  if (f.type === "bool") return f.value === true;
  if (f.value === null || f.value === undefined) return "";
  const text = String(f.value);
  return f.type === "json" ? prettyJson(text) : text;
}

export function initialValues(group: SettingsGroup): Values {
  return Object.fromEntries(group.fields.map((f) => [f.name, initialValue(f)]));
}

const text = (v: FormValue | undefined): string => (typeof v === "string" ? v.trim() : "");

function unchanged(f: SettingsField, now: FormValue | undefined, before: FormValue | undefined): boolean {
  if (f.type === "bool") return now === before;
  const a = text(now);
  const b = text(before);
  if (f.type === "json") return normalizedJson(a) === normalizedJson(b);
  if ((f.type === "int" || f.type === "float") && a !== "" && b !== "") return Number(a) === Number(b);
  return a === b;
}

/** The request body for a save or a test: only what changed. An empty object means "nothing changed". */
export function buildPayload(group: SettingsGroup, base: Values, values: Values, cleared: Cleared): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const f of group.fields) {
    const now = values[f.name];
    if (f.secret) {
      if (cleared[f.name]) out[f.name] = "";
      else if (text(now) !== "") out[f.name] = text(now);
      continue;
    }
    if (unchanged(f, now, base[f.name])) continue;
    if (f.type === "bool") out[f.name] = now === true;
    else if (f.type === "int" || f.type === "float") {
      const t = text(now);
      out[f.name] = t === "" ? "" : Number(t);
    } else out[f.name] = text(now);
  }
  return out;
}

export const hasChanges = (group: SettingsGroup, base: Values, values: Values, cleared: Cleared): boolean => Object.keys(buildPayload(group, base, values, cleared)).length > 0;

/** Field name → message. Required fields are always checked; formats are checked for fields the user changed. */
export function validate(group: SettingsGroup, base: Values, values: Values, cleared: Cleared): Record<string, string> {
  const errors: Record<string, string> = {};
  for (const f of group.fields) {
    const now = values[f.name];
    if (f.secret) {
      const keeps = f.has_value && !cleared[f.name];
      if (f.required && text(now) === "" && !keeps) errors[f.name] = `${f.label} is required.`;
      continue;
    }
    if (f.type === "bool") continue;
    const v = text(now);
    if (v === "") {
      if (f.required) errors[f.name] = `${f.label} is required.`;
      continue;
    }
    if (unchanged(f, now, base[f.name])) continue;
    const problem = formatProblem(f, v);
    if (problem) errors[f.name] = problem;
  }
  return errors;
}

function formatProblem(f: SettingsField, v: string): string | null {
  switch (f.type) {
    case "int":
      return /^-?\d+$/.test(v) ? null : "Enter a whole number.";
    case "float":
      return Number.isFinite(Number(v)) ? null : "Enter a number.";
    case "enum":
      return f.choices.includes(v) ? null : `Choose one of: ${f.choices.join(", ")}.`;
    case "url":
      return /^https?:\/\//i.test(v) ? null : "The address must start with https:// or http://.";
    case "pgurl":
      return /^postgres(ql)?:\/\//i.test(v) ? null : "The connection string must start with postgresql://.";
    case "regex":
      return /\(\?P<document_id>/.test(v) ? null : "The pattern must contain a (?P<document_id>...) group.";
    case "csv":
      return v.split(",").map((p) => p.trim()).filter(Boolean).every((p) => CSV_ITEM.test(p)) ? null : "Use letters, digits, _, - and . only, separated by commas.";
    case "json": {
      try {
        const parsed: unknown = JSON.parse(v);
        if (parsed === null || typeof parsed !== "object" || Array.isArray(parsed) || !Object.values(parsed).every((x) => typeof x === "string")) {
          return 'Enter a JSON object with text values, for example {"document_id": "doc_ref"}.';
        }
        return null;
      } catch (err) {
        return `Not valid JSON${err instanceof SyntaxError ? ` (${err.message.replace(/^JSON\.parse: /, "")})` : ""}.`;
      }
    }
    default:
      return null;
  }
}

/** Wide fields get a full row; short ones can share a row on larger screens. */
export function isWide(f: SettingsField): boolean {
  return f.secret || ["url", "pgurl", "json", "regex", "csv"].includes(f.type) || f.help.length > 90;
}

export type Verdict = "passed" | "warnings" | "failed";
export function verdict(result: Pick<TestResult, "ok" | "checks">): Verdict {
  if (!result.ok) return "failed";
  return result.checks.some((c) => c.status === "warn") ? "warnings" : "passed";
}

export const VERDICT_LABEL: Record<Verdict, string> = { passed: "passed", warnings: "passed with warnings", failed: "failed" };

/** Server messages are prefixed with the field label ("Chunk size: must be ..."): find the field they are about. */
export function fieldForServerError(group: SettingsGroup, message: string): string | null {
  const hit = group.fields.find((f) => message.startsWith(`${f.label}:`));
  return hit ? hit.name : null;
}

/** Turn a snake_case key into a sentence-case label. */
export const humanize = (key: string): string => {
  const s = key.replace(/_/g, " ").trim();
  return s.charAt(0).toUpperCase() + s.slice(1);
};
