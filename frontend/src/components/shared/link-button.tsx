import type { VariantProps } from "class-variance-authority";
import type { ReactNode } from "react";
import { Link, type LinkProps } from "react-router-dom";
import { cn } from "@/lib/cn";
import { buttonVariants } from "@/components/ui/button";

/** A router link that looks like a Button (so navigation is a real link: middle-click, copy address, screen readers). */
export function LinkButton({ variant, size, className, children, ...props }: LinkProps & VariantProps<typeof buttonVariants> & { children?: ReactNode }) {
  return (
    <Link className={cn(buttonVariants({ variant, size }), className)} {...props}>
      {children}
    </Link>
  );
}
