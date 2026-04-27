import type { ReactNode } from "react";
import { CircleHelp } from "lucide-react";

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
      className={cn("group/setting-label relative inline-flex cursor-help items-center gap-1.5", className)}
    >
      <span>{children}</span>
      <CircleHelp
        className="size-3.5 shrink-0 text-muted-foreground/80 transition-colors group-hover/setting-label:text-foreground group-focus-within/setting-label:text-foreground"
        aria-hidden="true"
      />
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
