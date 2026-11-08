/** One place that knows how to link to things, so pages never hand-build URLs. */
export const links = {
  issue: (id: string) => `/issues/${encodeURIComponent(id)}`,
  issues: (params: Record<string, string> = {}) => {
    const q = new URLSearchParams(params).toString();
    return q ? `/issues?${q}` : "/issues";
  },
  /** Opens the document drawer on the Documents page. */
  document: (tenant: string, documentId: string) => `/documents?${new URLSearchParams({ tenant, doc: documentId }).toString()}`,
  documents: (params: Record<string, string> = {}) => {
    const q = new URLSearchParams(params).toString();
    return q ? `/documents?${q}` : "/documents";
  },
  audit: (runId: string) => `/audit-history/${encodeURIComponent(runId)}`,
  settings: (tab?: string) => (tab ? `/settings?tab=${encodeURIComponent(tab)}` : "/settings"),
};

/** Same-origin API documentation (OpenAPI), served by the backend. */
export const API_DOCS_URL = "/docs";
