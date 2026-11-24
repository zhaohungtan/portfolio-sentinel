"use client";

import { Eye, EyeOff, RefreshCw } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { usePrivacy } from "@/components/privacy";

export function StatusBar({
  asOf,
  source,
  busy,
  onRefresh,
  onSyncNews,
}: {
  asOf: string | null;
  source: string | null;
  busy: boolean;
  onRefresh: () => void;
  onSyncNews: () => void;
}) {
  const { hidden, toggle } = usePrivacy();
  return (
    <header className="flex h-12 items-center gap-3 border-b border-zinc-200 bg-white px-3">
      <div className="leading-tight">
        <div className="text-[13px] font-medium tracking-wide">Portfolio Sentinel</div>
        <div className="text-[10px] tracking-[0.14em] text-zinc-500 uppercase">
          Sentinel // Risk & Macro Desk
        </div>
      </div>
      <div className="ml-auto flex items-center gap-2">
        <span className="num text-[11px] text-zinc-500">
          {asOf ? asOf.replace("T", " ").slice(0, 16) : "no sync"}
        </span>
        {source === "fixture" ? <Badge tone="warn">Mock data · holdings anonymized</Badge> : null}
        <Badge tone="lock">Read-only locked</Badge>
        <span className="num text-[11px] text-zinc-400">
          Gold {hidden ? "••••" : "$1,000"} free • 5.25% APR
        </span>
        <Button onClick={toggle} aria-pressed={hidden} title="Hide portfolio values">
          {hidden ? <EyeOff size={13} /> : <Eye size={13} />}
          {hidden ? "Values hidden" : "Hide values"}
        </Button>
        <Button onClick={onSyncNews} disabled={busy}>
          Sync live news
        </Button>
        <Button onClick={onRefresh} disabled={busy}>
          <RefreshCw size={13} className={busy ? "animate-spin" : ""} />
          Sync Robinhood
        </Button>
      </div>
    </header>
  );
}
