import { ChevronDown, Download, FileJson, FileSpreadsheet, FileText } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel, DropdownMenuTrigger, Tip } from "@/components/ui/menus";
import { api, errorMessage } from "@/lib/api";

type Format = "md" | "csv" | "json";

const FORMATS: { id: Format; label: string; note: string; ext: string; mime: string; icon: typeof FileText }[] = [
  { id: "md", label: "Markdown", note: "Readable report", ext: "md", mime: "text/markdown", icon: FileText },
  { id: "csv", label: "CSV", note: "One row per issue", ext: "csv", mime: "text/csv", icon: FileSpreadsheet },
  { id: "json", label: "JSON", note: "Everything, for tools", ext: "json", mime: "application/json", icon: FileJson },
];

/** Fetches the report through the API client (so the shared key header is sent when the server needs one) and saves it as a file. */
async function downloadReport(f: (typeof FORMATS)[number]): Promise<void> {
  const data = await api<string | object>(`/api/report?format=${f.id}`);
  const text = typeof data === "string" ? data : JSON.stringify(data, null, 2);
  const url = URL.createObjectURL(new Blob([text], { type: `${f.mime};charset=utf-8` }));
  const a = document.createElement("a");
  a.href = url;
  a.download = `rag-integrity-report.${f.ext}`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function ExportMenu({ disabledReason }: { disabledReason?: string | null }) {
  const [busy, setBusy] = useState<Format | null>(null);

  async function run(f: (typeof FORMATS)[number]) {
    if (busy) return;
    setBusy(f.id);
    try {
      await downloadReport(f);
      toast.success("Report downloaded", { description: `rag-integrity-report.${f.ext}` });
    } catch (err) {
      toast.error("Couldn't export the report", { description: errorMessage(err) });
    } finally {
      setBusy(null);
    }
  }

  if (disabledReason) {
    return (
      <Tip content={disabledReason}>
        <span tabIndex={0} className="inline-flex rounded-control">
          <Button variant="secondary" disabled>
            <Download className="h-4 w-4" aria-hidden /> Export report
          </Button>
        </span>
      </Tip>
    );
  }

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="secondary" loading={busy !== null}>
          {busy === null ? <Download className="h-4 w-4" aria-hidden /> : null}
          Export report
          <ChevronDown className="h-4 w-4 text-ink-2" aria-hidden />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent>
        <DropdownMenuLabel>Download as</DropdownMenuLabel>
        {FORMATS.map((f) => (
          <DropdownMenuItem key={f.id} onSelect={() => void run(f)}>
            <f.icon className="h-4 w-4 text-ink-2" aria-hidden />
            <span className="flex-1">{f.label}</span>
            <span className="text-support text-ink-2">{f.note}</span>
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
