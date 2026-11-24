import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

export function Badge({
  className,
  tone = "neutral",
  children,
}: {
  className?: string;
  tone?: "neutral" | "good" | "bad" | "warn" | "lock";
  children: ReactNode;
}) {
  const tones = {
    neutral: "text-zinc-600 border-zinc-300",
    good: "text-[#047857] border-[#047857]/40",
    bad: "text-[#be123c] border-[#be123c]/40",
    warn: "text-[#b45309] border-[#b45309]/40",
    lock: "text-zinc-700 border-zinc-300",
  };
  return (
    <span
      className={cn(
        "inline-flex items-center border px-1.5 py-0.5 text-[10px] tracking-wide uppercase",
        tones[tone],
        className,
      )}
    >
      {children}
    </span>
  );
}
