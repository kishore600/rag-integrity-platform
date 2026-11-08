/** Small helpers so every filter, tab and drawer on these pages lives in the URL (linkable, survives refresh). */
import { useCallback, useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useDebounced } from "@/hooks/use-debounced";

/** `null` or "" removes a parameter; `undefined` leaves it alone. */
export type ParamPatch = Record<string, string | null | undefined>;
export interface SetParamOptions {
  /** Defaults to true so typing in filters does not fill the back button history. */
  replace?: boolean;
  state?: unknown;
}

export function useParamState() {
  const [params, setParams] = useSearchParams();
  const set = useCallback(
    (patch: ParamPatch, opts: SetParamOptions = {}) => {
      setParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          for (const [k, v] of Object.entries(patch)) {
            if (v === undefined) continue;
            if (v === null || v === "") next.delete(k);
            else next.set(k, v);
          }
          return next;
        },
        { replace: opts.replace ?? true, state: opts.state },
      );
    },
    [setParams],
  );
  return { params, set };
}

/**
 * A text box bound to a URL parameter. `input` is what the user is typing; the URL (and so the query) only changes
 * after they pause, and the box follows the URL when something else changes it (for example "Clear filters").
 */
export function useDebouncedParam(key: string, ms = 300) {
  const { params, set } = useParamState();
  const urlValue = params.get(key) ?? "";
  const [input, setInput] = useState(urlValue);
  const debounced = useDebounced(input, ms);
  const lastWritten = useRef(urlValue);
  const urlRef = useRef(urlValue);
  urlRef.current = urlValue;
  const setRef = useRef(set);
  setRef.current = set;

  useEffect(() => {
    if (debounced === urlRef.current) return;
    lastWritten.current = debounced;
    setRef.current({ [key]: debounced || null });
  }, [debounced, key]);

  useEffect(() => {
    if (urlValue === lastWritten.current) return;
    lastWritten.current = urlValue;
    setInput(urlValue);
  }, [urlValue]);

  return { input, setInput, value: urlValue.trim() };
}

/** Reads a URL parameter that must be one of a known set; anything else (a hand-edited URL) falls back. */
export function oneOf<T extends string>(value: string | null, allowed: readonly T[], fallback: T): T {
  return allowed.includes(value as T) ? (value as T) : fallback;
}
