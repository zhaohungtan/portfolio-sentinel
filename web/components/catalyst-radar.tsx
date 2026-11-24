"use client";

import { Money } from "@/components/privacy";
import type { Catalyst } from "@/lib/types";

export function CatalystRadar({ events }: { events?: Catalyst[] | null }) {
  const rows = events ?? [];
  const peak = Math.max(...rows.map((event) => event.exposure_usd || 0), 1);
  return (
    <section className="card flex min-h-[280px] flex-col">
      <header className="border-b border-zinc-200 px-3 py-2 text-[10px] tracking-[0.16em] text-zinc-500 uppercase">
        30-day catalyst radar
      </header>
      <div className="flex-1 overflow-auto">
        {rows.length === 0 ? (
          <p className="p-3 text-xs text-zinc-500">Nothing in the next 30 days.</p>
        ) : (
          rows.map((event) => (
            <div key={`${event.kind}-${event.date}-${event.name}`} className="border-b border-zinc-200 px-3 py-2">
              <div className="flex items-baseline justify-between gap-2">
                <span className="text-[12px]">{event.name}</span>
                <span className="num text-[11px] text-[#b45309]">{event.days_remaining}d</span>
              </div>
              <div className="mt-1 text-[10px] text-zinc-500">
                {event.date}
                {event.time_et ? ` ${event.time_et} ET` : ""}
                {event.held_ticker ? ` · ${event.held_ticker}` : ""}
              </div>
              <div className="mt-1.5 h-1 bg-zinc-200">
                <div
                  className="h-1"
                  style={{
                    width: `${Math.max(4, (event.exposure_usd / peak) * 100)}%`,
                    background: event.kind === "macro" ? "#b45309" : "#18181b",
                  }}
                />
              </div>
              <div className="num mt-1 text-[10px] text-zinc-400">
                <Money value={event.exposure_usd} />
                {event.implied_move_pct != null ? ` · ±${(event.implied_move_pct * 100).toFixed(1)}%` : ""}
              </div>
            </div>
          ))
        )}
      </div>
    </section>
  );
}
