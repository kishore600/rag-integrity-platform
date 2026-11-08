import { cva, type VariantProps } from "class-variance-authority";
import { Loader2 } from "lucide-react";
import { forwardRef, type ButtonHTMLAttributes } from "react";
import { cn } from "@/lib/cn";

export const buttonVariants = cva(
  "inline-flex shrink-0 items-center justify-center gap-2 whitespace-nowrap rounded-control text-body font-medium transition-colors disabled:pointer-events-none disabled:opacity-50",
  {
    variants: {
      variant: {
        primary: "bg-brand text-white shadow-card hover:bg-brand-hover",
        secondary: "border border-line bg-workspace text-ink shadow-card hover:bg-surface",
        ghost: "text-ink-2 hover:bg-surface hover:text-ink",
        danger: "bg-critical text-white shadow-card hover:bg-red-700",
        "danger-outline": "border border-line bg-workspace text-critical shadow-card hover:bg-critical-bg",
        link: "h-auto p-0 text-brand hover:text-brand-hover hover:underline",
      },
      size: { sm: "h-8 px-3 text-support", md: "h-9 px-3.5", lg: "h-10 px-4", icon: "h-9 w-9 p-0", "icon-sm": "h-8 w-8 p-0" },
    },
    defaultVariants: { variant: "secondary", size: "md" },
  },
);

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement>, VariantProps<typeof buttonVariants> {
  loading?: boolean;
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button({ className, variant, size, loading, disabled, children, type = "button", ...props }, ref) {
  return (
    <button ref={ref} type={type} className={cn(buttonVariants({ variant, size }), className)} disabled={disabled || loading} aria-busy={loading || undefined} {...props}>
      {loading ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : null}
      {children}
    </button>
  );
});
