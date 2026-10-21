import type { ReactNode } from "react";
import { cn } from "../../lib/utils";

export function Badge({
  className,
  tone = "muted",
  children,
}: {
  className?: string;
  tone?: "muted" | "amber" | "coral" | "moss" | "steel";
  children: ReactNode;
}) {
  const tones = {
    muted: "bg-line/60 text-muted",
    amber: "bg-amber/20 text-amber",
    coral: "bg-coral/20 text-coral",
    moss: "bg-moss/20 text-moss",
    steel: "bg-steel/20 text-steel",
  };
  return (
    <span className={cn("inline-flex items-center rounded px-1.5 py-0.5 text-[11px] font-medium", tones[tone], className)}>
      {children}
    </span>
  );
}
