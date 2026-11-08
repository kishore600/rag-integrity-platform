import { useEffect, useState } from "react";

/** Returns `value` after it has stopped changing for `ms`. Used so typing in a search box does not hit the API on every key. */
export function useDebounced<T>(value: T, ms = 300): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = window.setTimeout(() => setV(value), ms);
    return () => window.clearTimeout(t);
  }, [value, ms]);
  return v;
}
