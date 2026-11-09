import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useDebounced } from "@/hooks/use-debounced";

/**
 * A search box kept in the address bar (`?q=...`), so a filtered view can be linked to and survives a refresh.
 * `text` follows every keystroke (the table filters on it at once); the address is only updated once typing settles.
 */
export function useUrlSearch(name = "q"): { text: string; setText: (v: string) => void } {
  const [params, setParams] = useSearchParams();
  const param = params.get(name) ?? "";
  const [text, setText] = useState(param);
  const settled = useDebounced(text, 300);

  useEffect(() => {
    if (settled === param) return;
    setParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        if (settled) next.set(name, settled);
        else next.delete(name);
        return next;
      },
      { replace: true },
    );
    // only when the typed value settles; an outside change of the address is handled below
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [settled]);

  useEffect(() => {
    // the address changed from outside (back button, a link): show it in the box
    if (param !== settled) setText(param);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [param]);

  return { text, setText };
}
