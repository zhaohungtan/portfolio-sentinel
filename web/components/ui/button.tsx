import * as React from "react";
import { cn } from "@/lib/utils";

export function Button({
  className,
  ...props
}: React.ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button
      className={cn(
        "inline-flex h-7 items-center gap-1.5 border border-zinc-300 bg-white px-2.5 text-[11px] font-medium tracking-wide text-zinc-800 uppercase hover:bg-zinc-100 disabled:opacity-50",
        className,
      )}
      {...props}
    />
  );
}
