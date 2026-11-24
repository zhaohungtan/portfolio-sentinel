"use client";

import { useState } from "react";
import { Bar, BarChart, Cell, ResponsiveContainer } from "recharts";
import { Money } from "@/components/privacy";
import { pct, plainPct } from "@/lib/format";
import type { Dashboard } from "@/lib/types";

function tone(value: number | null | undefined) {
  if (value == null) return "text-zinc-400";
  if (value > 0.02) return "text-[#047857]";
  if (value < -0.02) return "text-[#be123c]";
  return "text-[#b45309]";
}

function label(value: number | null | undefined) {
  if (value == null) return "No tape";
  if (value > 0.05) return "Positive";
  if (value < -0.05) return "Negative";
  return "Neutral";
}

export function MorningCards({ data }: { data: Dashboard }) {
  const probs = data.margin?.probabilities ?? {};
  const drops = data.margin?.drops;
  const perf = data.performance;
  const next = data.next_catalyst;
  const sentiment = data.sentiment ?? {};
  const tail = data.margin?.pnl_percentiles_21d ?? [];
  const scenarios = data.margin?.scenarios ?? [];
  const [scenarioId, setScenarioId] = useState("current");
  const scenario = scenarios.find((item) => item.id === scenarioId) ?? scenarios[0];
  const bufferUsd = scenario?.buffer_usd ?? data.margin?.stressed_static_buffer_usd ?? drops?.stressed_static_buffer_usd ?? 0;
  const bufferPct = scenario?.buffer_pct ?? data.margin?.stressed_static_buffer_pct ?? drops?.stressed_static_buffer_pct ?? 0;
  const gold = scenario?.daily_gold ?? data.margin?.daily_gold ?? perf.daily_gold_carry;
  const stressed5 = scenario?.stressed_5d ?? probs["5"]?.stressed ?? 0;
  const stressed21 = scenario?.stressed_21d ?? probs["21"]?.stressed ?? 0;
  const cash = perf.same_cash;
  return (
    <section className="grid grid-cols-4 items-start gap-2">
      <article className="card flex h-[228px] flex-col p-3">
        <h2 className="text-[10px] tracking-[0.16em] text-zinc-500 uppercase">Margin call risk</h2>
        <div className="mt-1 flex flex-wrap gap-1">
          {(scenarios.length ? scenarios : [{ id: "current", label: "Current" }]).map((item) => (
            <button
              key={item.id}
              onClick={() => setScenarioId(item.id)}
              className={`border px-1.5 py-0.5 text-[10px] uppercase ${
                (scenario?.id ?? "current") === item.id
                  ? "border-zinc-900 text-zinc-900"
                  : "border-zinc-200 text-zinc-500"
              }`}
            >
              {item.label}
            </button>
          ))}
        </div>
        <div className="mt-2 grid grid-cols-3 gap-2">
          <div>
            <div className="text-[10px] text-zinc-500">1D</div>
            <div className="num text-lg text-[#be123c]">{plainPct(probs["1"]?.stressed ?? 0, 2)}</div>
          </div>
          <div>
            <div className="text-[10px] text-zinc-500">5D</div>
            <div className="num text-lg text-[#be123c]">{plainPct(stressed5, 2)}</div>
          </div>
          <div>
            <div className="text-[10px] text-zinc-500">21D</div>
            <div className="num text-lg text-[#be123c]">{plainPct(stressed21, 2)}</div>
          </div>
        </div>
        <div className="mt-1 text-[11px] text-zinc-700">
          50% buffer <Money value={bufferUsd} /> · <span className="num">{plainPct(bufferPct, 2)}</span>
        </div>
        <div className="text-[10px] text-zinc-500">
          Gold <Money value={gold} digits={2} />/day
        </div>
        <div className="text-[10px] text-zinc-500">
          25% buffer <Money value={drops?.baseline_drop_usd ?? 0} /> ·{" "}
          <span className="num">{plainPct(drops?.baseline_drop_pct ?? 0)}</span>
        </div>
        <div className="mt-auto h-10">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={tail}>
              <Bar dataKey="pnl_usd" isAnimationActive={false}>
                {tail.map((entry) => (
                  <Cell key={entry.percentile} fill={entry.pnl_usd < 0 ? "#be123c" : "#047857"} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      </article>

      <article className="card flex min-h-[228px] flex-col p-3">
        <h2 className="text-[10px] tracking-[0.16em] text-zinc-500 uppercase">Strategy verdict</h2>
        {cash == null ? (
          <p className="mt-2 text-[11px] text-[#b45309]">The comparison needs all-time realized profit on the saved book.</p>
        ) : (
          <>
            <div className="mt-2">
              <div className="text-[10px] text-zinc-500">Estimated money in</div>
              <div className="num text-xl text-zinc-900">
                <Money value={cash.money_in} />
              </div>
            </div>
            <div className="mt-2">
              <div className="text-[10px] text-zinc-500">Now</div>
              <div className={`num text-xl ${tone(cash.change_pct)}`}>
                <Money value={cash.net_equity} />
              </div>
              <div className={`num text-[11px] ${tone(cash.change_pct)}`}>
                <Money value={cash.change_usd} /> · {pct(cash.change_pct)}
              </div>
            </div>
            <div className="mt-2 grid grid-cols-2 gap-2">
              <Benchmark name="QQQ" ending={cash.qqq_now} gap={cash.alpha_qqq} />
              <Benchmark name="S&P 500" ending={cash.spy_now} gap={cash.alpha_spy} />
            </div>
          </>
        )}
      </article>

      <article className="card flex h-[228px] flex-col p-3">
        <h2 className="text-[10px] tracking-[0.16em] text-zinc-500 uppercase">Next catalyst</h2>
        {next ? (
          <>
            <div className="mt-2 text-sm leading-5">{next.name}</div>
            <div className="num mt-1 text-2xl text-[#b45309]">{next.days_remaining}d</div>
            <div className="num text-[11px] text-zinc-400">
              {next.date}
              {next.time_et ? ` ${next.time_et} ET` : ""}
              {next.held_ticker ? ` · ${next.held_ticker}` : ""}
            </div>
            <div className="mt-auto text-[11px] text-zinc-700">
              Implied gap <span className="num">{next.implied_move_pct == null ? "—" : `±${(next.implied_move_pct * 100).toFixed(1)}%`}</span>
              <span className="text-zinc-500"> {next.implied_move_source}</span>
            </div>
          </>
        ) : (
          <p className="mt-3 text-xs text-zinc-500">No upcoming catalyst.</p>
        )}
      </article>

      <article className="card flex h-[228px] flex-col p-3">
        <h2 className="text-[10px] tracking-[0.16em] text-zinc-500 uppercase">7-day news polarity</h2>
        <div className="mt-2 grid grid-cols-2 gap-2 text-[11px]">
          <Polarity name="Macro 24h" value={sentiment.macro_24h} />
          <Polarity name="Book 24h" value={sentiment.portfolio_24h} />
          <Polarity name="Macro 7d" value={sentiment.macro_7d} />
          <Polarity name="Book 7d" value={sentiment.portfolio_7d} />
        </div>
      </article>
    </section>
  );
}

function Benchmark({
  name,
  ending,
  gap,
}: {
  name: string;
  ending?: number | null;
  gap?: number | null;
}) {
  const beat = (gap ?? 0) > 0;
  return (
    <div>
      <div className="text-[10px] text-zinc-500">vs {name}</div>
      <div className="num text-sm text-zinc-900">
        <Money value={ending} />
      </div>
      <div className={`num text-[11px] ${gap == null ? "text-zinc-400" : beat ? "text-[#047857]" : "text-[#be123c]"}`}>
        {gap == null ? "—" : `${beat ? "Beat" : "Lost"} ${plainPct(Math.abs(gap))}`}
      </div>
    </div>
  );
}

function Polarity({ name, value }: { name: string; value: number | null | undefined }) {
  return (
    <div className="border border-zinc-200 px-2 py-1.5">
      <div className="text-[10px] text-zinc-500 uppercase">{name}</div>
      <div className={`num text-sm ${tone(value)}`}>{label(value)}</div>
    </div>
  );
}
