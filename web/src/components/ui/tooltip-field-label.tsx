import type { ReactNode } from "react";

import { FieldLabel } from "@/components/ui/field";
import { cn } from "@/lib/utils";

interface TooltipFieldLabelProps {
  children: ReactNode;
  tooltip: string;
  htmlFor?: string;
  className?: string;
}

export function TooltipFieldLabel({
  children,
  tooltip,
  htmlFor,
  className,
}: TooltipFieldLabelProps) {
  return (
    <FieldLabel
      htmlFor={htmlFor}
      className={cn("group/setting-label relative cursor-help items-center", className)}
    >
      <span>{children}</span>
      <span
        className={cn(
          "pointer-events-none absolute left-0 top-full z-20 mt-2 w-64 rounded-md border border-border/80 bg-popover px-3 py-2 text-xs font-normal text-popover-foreground shadow-lg opacity-0 transition-opacity duration-150",
          "group-hover/setting-label:opacity-100 group-focus-within/setting-label:opacity-100"
        )}
        role="tooltip"
      >
        {tooltip}
      </span>
    </FieldLabel>
  );
}
