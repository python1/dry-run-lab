import * as React from "react";
import { cn } from "../../lib/utils";

export function Textarea({ className, ...props }: React.ComponentProps<"textarea">) {
  return (
    <textarea
      className={cn(
        "w-full rounded-md border border-line bg-ink px-3 py-2 font-mono text-xs leading-5 text-paper outline-none placeholder:text-muted focus-visible:ring-2 focus-visible:ring-amber",
        className,
      )}
      {...props}
    />
  );
}
