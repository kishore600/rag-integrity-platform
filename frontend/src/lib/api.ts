/** Thin fetch wrapper. Session auth is an HttpOnly cookie managed by the server: this code never sees or stores a credential. */

export class ApiError extends Error {
  status: number;
  body: Record<string, unknown> | null;
  constructor(message: string, status: number, body: Record<string, unknown> | null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.body = body;
  }
  /** True when the server says a required connection has not been configured yet. */
  get setupIncomplete(): boolean {
    return !!(this.body && this.body.setup_incomplete);
  }
}

let onUnauthorized: (() => void) | null = null;
/** The auth gate registers here so an expired session sends the user back to the sign-in screen. */
export function setUnauthorizedHandler(fn: (() => void) | null): void {
  onUnauthorized = fn;
}

// Single-user modes can be protected by a shared RAGI_API_KEY. It is kept in memory only (never in browser storage).
let memoryApiKey = "";
export function setApiKey(key: string): void {
  memoryApiKey = key;
}

interface Options {
  method?: "GET" | "POST" | "PUT" | "DELETE";
  body?: unknown;
  /** Do not treat a 401 as "session expired" (used for the sign-in calls themselves). */
  anon?: boolean;
  signal?: AbortSignal;
}

export async function api<T>(path: string, opts: Options = {}): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json" };
  if (opts.body !== undefined) headers["Content-Type"] = "application/json";
  if (memoryApiKey) headers["X-API-Key"] = memoryApiKey;
  const res = await fetch(path, {
    method: opts.method ?? "GET",
    headers,
    credentials: "same-origin",
    body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
    signal: opts.signal,
  });
  if (res.status === 401 && !opts.anon) onUnauthorized?.();
  if (!res.ok) {
    let detail = res.statusText || `Request failed (${res.status})`;
    let body: Record<string, unknown> | null = null;
    try {
      body = (await res.json()) as Record<string, unknown>;
      const d = body.detail;
      detail = typeof d === "string" ? d : d !== undefined ? JSON.stringify(d) : detail;
    } catch {
      /* not JSON */
    }
    throw new ApiError(detail, res.status, body);
  }
  const type = res.headers.get("content-type") ?? "";
  return (type.includes("json") ? res.json() : res.text()) as Promise<T>;
}

export const get = <T>(path: string, signal?: AbortSignal) => api<T>(path, { signal });
export const post = <T>(path: string, body: unknown = {}) => api<T>(path, { method: "POST", body });
export const put = <T>(path: string, body: unknown) => api<T>(path, { method: "PUT", body });
export const del = <T>(path: string) => api<T>(path, { method: "DELETE" });

/** Build a query string, skipping empty values. */
export function qs(params: Record<string, string | number | boolean | undefined | null>): string {
  const sp = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === null || v === "" || v === false) continue;
    sp.set(k, String(v));
  }
  const s = sp.toString();
  return s ? `?${s}` : "";
}

/** A message that is safe to show: ApiError details are already scrubbed by the server. */
export function errorMessage(err: unknown): string {
  if (err instanceof ApiError) return err.message;
  if (err instanceof Error) return err.message;
  return "Something went wrong.";
}
