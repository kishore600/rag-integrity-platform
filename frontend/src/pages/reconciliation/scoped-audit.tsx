import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Field, Select, Switch } from "@/components/ui/form";
import { Modal } from "@/components/ui/overlays";
import { formatNumber } from "@/lib/format";
import type { AuditRequest, TenantHealth } from "@/types/api";

/** Audit one tenant instead of everything. The tenant list is the real one from the last audit. */
export function ScopedAuditModal({ open, onOpenChange, tenants, onRun }: { open: boolean; onOpenChange: (open: boolean) => void; tenants: TenantHealth[]; onRun: (req: AuditRequest) => void }) {
  const [tenant, setTenant] = useState("");
  const [probe, setProbe] = useState(true);

  // start from the first tenant each time the dialog opens, and never keep one that no longer exists
  useEffect(() => {
    if (open) setTenant((cur) => (tenants.some((t) => t.tenant_id === cur) ? cur : (tenants[0]?.tenant_id ?? "")));
  }, [open, tenants]);

  function submit() {
    if (!tenant) return;
    onRun({ tenant, probe });
    onOpenChange(false);
  }

  return (
    <Modal
      open={open}
      onOpenChange={onOpenChange}
      title="Scoped audit"
      description="Check a single tenant. It is faster than a full audit and leaves other tenants untouched."
      size="sm"
      footer={
        <>
          <Button variant="secondary" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button variant="primary" onClick={submit} disabled={!tenant}>
            Run scoped audit
          </Button>
        </>
      }
    >
      {tenants.length === 0 ? (
        <p className="text-body text-ink-2">There are no tenants to choose from yet. Run a full audit first, then come back to audit a single tenant.</p>
      ) : (
        <form
          className="space-y-5"
          onSubmit={(e) => {
            e.preventDefault();
            submit();
          }}
        >
          <Field label="Tenant" required>
            {({ id }) => (
              <Select id={id} value={tenant} onChange={(e) => setTenant(e.target.value)}>
                {tenants.map((t) => (
                  <option key={t.tenant_id} value={t.tenant_id}>
                    {t.tenant_id} ({formatNumber(t.documents)} {t.documents === 1 ? "document" : "documents"})
                  </option>
                ))}
              </Select>
            )}
          </Field>
          <div className="flex items-start justify-between gap-4">
            <div className="min-w-0">
              <label htmlFor="scoped-probe" className="block text-body font-medium text-ink">
                Probe retrieval for the worst findings
              </label>
              <p className="mt-0.5 text-support text-ink-2">Queries your index to confirm that the most serious findings really affect search results. It takes a little longer.</p>
            </div>
            <Switch id="scoped-probe" checked={probe} onChange={setProbe} label="Probe retrieval for the worst findings" />
          </div>
        </form>
      )}
    </Modal>
  );
}
