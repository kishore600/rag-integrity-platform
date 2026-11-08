import * as DropdownMenuPrimitive from "@radix-ui/react-dropdown-menu";
import * as TabsPrimitive from "@radix-ui/react-tabs";
import * as TooltipPrimitive from "@radix-ui/react-tooltip";
import type { ComponentPropsWithoutRef, ReactNode } from "react";
import { cn } from "@/lib/cn";

// ---- dropdown menu --------------------------------------------------------------------------------------
export const DropdownMenu = DropdownMenuPrimitive.Root;
export const DropdownMenuTrigger = DropdownMenuPrimitive.Trigger;
export const DropdownMenuSeparator = () => <DropdownMenuPrimitive.Separator className="my-1 h-px bg-line" />;

export function DropdownMenuContent({ className, align = "end", ...props }: ComponentPropsWithoutRef<typeof DropdownMenuPrimitive.Content>) {
  return (
    <DropdownMenuPrimitive.Portal>
      <DropdownMenuPrimitive.Content
        align={align}
        sideOffset={6}
        className={cn("anim-pop z-50 min-w-[200px] rounded-card border border-line bg-workspace p-1 shadow-pop", className)}
        {...props}
      />
    </DropdownMenuPrimitive.Portal>
  );
}

export function DropdownMenuItem({ className, destructive, ...props }: ComponentPropsWithoutRef<typeof DropdownMenuPrimitive.Item> & { destructive?: boolean }) {
  return (
    <DropdownMenuPrimitive.Item
      className={cn(
        "flex cursor-pointer select-none items-center gap-2 rounded-control px-2.5 py-2 text-body outline-none data-[disabled]:pointer-events-none data-[highlighted]:bg-surface data-[disabled]:opacity-50",
        destructive ? "text-critical" : "text-ink",
        className,
      )}
      {...props}
    />
  );
}

export function DropdownMenuLabel({ children, className }: { children: ReactNode; className?: string }) {
  return <DropdownMenuPrimitive.Label className={cn("px-2.5 py-1.5 text-support text-ink-2", className)}>{children}</DropdownMenuPrimitive.Label>;
}

// ---- tabs -----------------------------------------------------------------------------------------------
export const Tabs = TabsPrimitive.Root;

export function TabsList({ className, ...props }: ComponentPropsWithoutRef<typeof TabsPrimitive.List>) {
  return <TabsPrimitive.List className={cn("flex gap-1 overflow-x-auto overflow-y-hidden border-b border-line [scrollbar-width:none] [&::-webkit-scrollbar]:hidden", className)} {...props} />;
}

export function TabsTrigger({ className, ...props }: ComponentPropsWithoutRef<typeof TabsPrimitive.Trigger>) {
  return (
    <TabsPrimitive.Trigger
      className={cn(
        "-mb-px inline-flex items-center gap-2 whitespace-nowrap border-b-2 border-transparent px-3 py-2.5 text-body font-medium text-ink-2 transition-colors hover:text-ink data-[state=active]:border-brand data-[state=active]:text-brand",
        className,
      )}
      {...props}
    />
  );
}

export function TabsContent({ className, ...props }: ComponentPropsWithoutRef<typeof TabsPrimitive.Content>) {
  return <TabsPrimitive.Content className={cn("pt-5 focus-visible:ring-0", className)} {...props} />;
}

// ---- tooltip --------------------------------------------------------------------------------------------
export const TooltipProvider = ({ children }: { children: ReactNode }) => <TooltipPrimitive.Provider delayDuration={250}>{children}</TooltipPrimitive.Provider>;

export function Tip({ content, children, side = "top" }: { content: ReactNode; children: ReactNode; side?: "top" | "right" | "bottom" | "left" }) {
  return (
    <TooltipPrimitive.Root>
      <TooltipPrimitive.Trigger asChild>{children}</TooltipPrimitive.Trigger>
      <TooltipPrimitive.Portal>
        <TooltipPrimitive.Content side={side} sideOffset={6} className="anim-pop z-[60] max-w-xs rounded-control bg-ink px-2.5 py-1.5 text-support text-white shadow-pop">
          {content}
        </TooltipPrimitive.Content>
      </TooltipPrimitive.Portal>
    </TooltipPrimitive.Root>
  );
}
