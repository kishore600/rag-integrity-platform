import { useCallback, useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useDebounced } from "@/hooks/use-debounced";

/** One value kept in the address bar (`?name=value`), so a filtered view can be linked to and survives a refresh. */
export function useUrlParam(name: string, fallback = ""): [string, (value: string) => void] {
  const [params, setParams] = useSearchParams();
  const value = params.get(name) ?? fallback;
  const set = useCallback(
    (next: string) =>
      setParams(
        (prev) => {
          const n = new URLSearchParams(prev);
          if (!next || next === fallback) n.delete(name);
          else n.set(name, next);
          return n;
        },
        { replace: true },
      ),
    [setParams, name, fallback],
  );
  return [value, set];
}

/**
 * Removes several parameters in one navigation. Calling the single-value setters one after another in the same event would lose
 * all but the last change, because each one starts from the address as it was at the last render.
 */
export function useClearParams(): (names: string[]) => void {
  const [, setParams] = useSearchParams();
  return useCallback(
    (names: string[]) =>
      setParams(
        (prev) => {
          const n = new URLSearchParams(prev);
          names.forEach((x) => n.delete(x));
          return n;
        },
        { replace: true },
      ),
    [setParams],
  );
}

/** A search box value: `text` follows every keystroke, `value` is the debounced one that is written to the address bar and used for filtering. */
export function useUrlSearch(name = "q"): { text: string; setText: (v: string) => void; value: string } {
  const [param, setParam] = useUrlParam(name);
  const [text, setText] = useState(param);
  const value = useDebounced(text, 300);

  useEffect(() => {
    if (value !== param) setParam(value);
    // only when the typed value settles; an outside change of the address is handled below
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value]);

  useEffect(() => {
    // the address changed from outside (back button, "clear filters"): show it in the box
    if (param !== value) setText(param);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [param]);

  return { text, setText, value };
}
