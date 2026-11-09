import { Download } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Tip } from "@/components/ui/menus";
import { api, errorMessage } from "@/lib/api";

const FILE_NAME = "rag-isolation-report.md";

/** Fetches the evidence page through the API client (so the shared key header is sent when the server needs one) and saves it as a file. */
async function downloadReport(): Promise<void> {
  const data = await api<string | object>("/api/isolation/report?format=md");
  const text = typeof data === "string" ? data : JSON.stringify(data, null, 2);
  const url = URL.createObjectURL(new Blob([text], { type: "text/markdown;charset=utf-8" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = FILE_NAME;
  document.body.appendChild(a);
  a.click();
  a.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

/** The evidence report as a download. Disabled, with the reason in a tooltip, until a full audit has produced a result. */
export function ReportButton({ disabledReason }: { disabledReason?: string | null }) {
  const [busy, setBusy] = useState(false);

  async function run() {
    if (busy) return;
    setBusy(true);
    try {
      await downloadReport();
      toast.success("Evidence report downloaded", { description: FILE_NAME });
    } catch (err) {
      toast.error("Couldn't download the evidence report", { description: errorMessage(err) });
    } finally {
      setBusy(false);
    }
  }

  const label = "Download evidence report (.md)";

  if (disabledReason) {
    return (
      <Tip content={disabledReason}>
        <span tabIndex={0} className="inline-flex rounded-control">
          <Button variant="secondary" disabled>
            <Download className="h-4 w-4" aria-hidden /> {label}
          </Button>
        </span>
      </Tip>
    );
  }

  return (
    <Button variant="secondary" onClick={() => void run()} loading={busy}>
      {busy ? null : <Download className="h-4 w-4" aria-hidden />} {label}
    </Button>
  );
}
