import { X } from "lucide-react";
import type { ReactNode } from "react";
import { cn } from "@/lib/cn";
import { Button } from "@/components/ui/button";
import { Select } from "@/components/ui/form";

export function FilterBar({ children, onClear, active, className }: { children: ReactNode; onClear?: () => void; active?: boolean; className?: string }) {
  return (
    <div className={cn("flex flex-wrap items-end gap-3 border-b border-line px-4 py-3", className)} role="search">
      {children}
      {onClear && active ? (
        <Button variant="ghost" size="sm" onClick={onClear} className="ml-auto">
          <X className="h-3.5 w-3.5" /> Clear filters
        </Button>
      ) : null}
    </div>
  );
}

export function FilterSelect({ label, value, onChange, options, className }: { label: string; value: string; onChange: (v: string) => void; options: { value: string; label: string }[]; className?: string }) {
  return (
    <label className={cn("block min-w-[140px]", className)}>
      <span className="mb-1 block text-support text-ink-2">{label}</span>
      <Select value={value} onChange={(e) => onChange(e.target.value)} aria-label={label}>
        {options.map((o) => (
          <option key={o.value} value={o.value}>{o.label}</option>
        ))}
      </Select>
    </label>
  );
}
