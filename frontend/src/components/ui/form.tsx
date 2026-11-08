import { ChevronDown, Search, X } from "lucide-react";
import { forwardRef, useId, type InputHTMLAttributes, type ReactNode, type SelectHTMLAttributes, type TextareaHTMLAttributes } from "react";
import { cn } from "@/lib/cn";

const control =
  "w-full rounded-control border border-line-strong bg-workspace px-3 text-body text-ink placeholder:text-ink-3 transition-colors hover:border-ink-3 focus:border-brand focus:outline-none focus:ring-2 focus:ring-brand/20 disabled:cursor-not-allowed disabled:bg-surface disabled:text-ink-2";

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement> & { invalid?: boolean }>(function Input({ className, invalid, ...props }, ref) {
  return <input ref={ref} className={cn(control, "h-9", invalid && "border-critical focus:border-critical focus:ring-critical/20", className)} aria-invalid={invalid || undefined} {...props} />;
});

export const Textarea = forwardRef<HTMLTextAreaElement, TextareaHTMLAttributes<HTMLTextAreaElement> & { invalid?: boolean }>(function Textarea({ className, invalid, ...props }, ref) {
  return <textarea ref={ref} className={cn(control, "min-h-[84px] py-2", invalid && "border-critical", className)} aria-invalid={invalid || undefined} {...props} />;
});

/** A native select, styled. Native keeps it accessible, keyboard friendly and correct on mobile. */
export const Select = forwardRef<HTMLSelectElement, SelectHTMLAttributes<HTMLSelectElement>>(function Select({ className, children, ...props }, ref) {
  return (
    <div className="relative">
      <select ref={ref} className={cn(control, "h-9 cursor-pointer appearance-none pr-8", className)} {...props}>
        {children}
      </select>
      <ChevronDown className="pointer-events-none absolute right-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-2" aria-hidden />
    </div>
  );
});

export function SearchInput({ value, onChange, placeholder = "Search", className, ...props }: { value: string; onChange: (v: string) => void; placeholder?: string; className?: string } & Omit<InputHTMLAttributes<HTMLInputElement>, "value" | "onChange">) {
  return (
    <div className={cn("relative", className)}>
      <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-3" aria-hidden />
      <Input value={value} onChange={(e) => onChange(e.target.value)} placeholder={placeholder} className="pl-9 pr-8" aria-label={placeholder} {...props} />
      {value ? (
        <button type="button" onClick={() => onChange("")} className="absolute right-2 top-1/2 -translate-y-1/2 rounded p-1 text-ink-3 hover:text-ink" aria-label="Clear search">
          <X className="h-3.5 w-3.5" />
        </button>
      ) : null}
    </div>
  );
}

export function Label({ children, htmlFor, required, className }: { children: ReactNode; htmlFor?: string; required?: boolean; className?: string }) {
  return (
    <label htmlFor={htmlFor} className={cn("mb-1.5 block text-support font-medium text-ink", className)}>
      {children}
      {required ? <span className="ml-0.5 text-critical" aria-hidden>*</span> : null}
    </label>
  );
}

/** Label + control + help/error text with the ids wired for screen readers. The render prop receives the id and aria attributes. */
export function Field({ label, help, error, required, children, className }: { label: string; help?: ReactNode; error?: string | null; required?: boolean; children: (p: { id: string; "aria-describedby"?: string; invalid: boolean }) => ReactNode; className?: string }) {
  const id = useId();
  const describedBy = error ? `${id}-err` : help ? `${id}-help` : undefined;
  return (
    <div className={className}>
      <Label htmlFor={id} required={required}>{label}</Label>
      {children({ id, "aria-describedby": describedBy, invalid: !!error })}
      {error ? <p id={`${id}-err`} className="mt-1.5 text-support text-critical" role="alert">{error}</p> : help ? <p id={`${id}-help`} className="mt-1.5 text-support text-ink-2">{help}</p> : null}
    </div>
  );
}

export function Switch({ checked, onChange, label, disabled, id }: { checked: boolean; onChange: (v: boolean) => void; label: string; disabled?: boolean; id?: string }) {
  return (
    <button
      id={id}
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={cn("relative inline-flex h-5 w-9 shrink-0 items-center rounded-full transition-colors disabled:opacity-50", checked ? "bg-brand" : "bg-line-strong")}
    >
      <span className={cn("inline-block h-4 w-4 rounded-full bg-white shadow transition-transform", checked ? "translate-x-[18px]" : "translate-x-0.5")} />
    </button>
  );
}

export const Checkbox = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(function Checkbox({ className, ...props }, ref) {
  return <input ref={ref} type="checkbox" className={cn("h-4 w-4 cursor-pointer rounded border-line-strong accent-brand", className)} {...props} />;
});
