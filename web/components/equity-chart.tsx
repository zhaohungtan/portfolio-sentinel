"use client";

import { useEffect, useRef } from "react";
import { ColorType, createChart, LineSeries, type IChartApi } from "lightweight-charts";
import { usePrivacy } from "@/components/privacy";
import { usd } from "@/lib/format";
import type { Dashboard } from "@/lib/types";

const SERIES = [
  { key: "portfolio", title: "Portfolio", color: "#18181b", width: 2 },
  { key: "QQQ", title: "QQQ", color: "#b45309", width: 1 },
  { key: "SPY", title: "S&P 500", color: "#047857", width: 1 },
] as const;

export function EquityChart({
  performance,
  synthetic,
}: {
  performance: Dashboard["performance"];
  synthetic: boolean;
}) {
  const host = useRef<HTMLDivElement>(null);
  const { hidden } = usePrivacy();
  const same = performance.same_cash;
  const curve = same?.portfolio ?? [];
  const qqq = same?.benchmarks?.QQQ ?? [];
  const spy = same?.benchmarks?.SPY ?? [];

  useEffect(() => {
    const element = host.current;
    if (!element || curve.length === 0) return;
    const chart: IChartApi = createChart(element, {
      autoSize: true,
      layout: {
        background: { type: ColorType.Solid, color: "#ffffff" },
        textColor: "#52525b",
        fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
      },
      grid: {
        vertLines: { color: "#e4e4e7" },
        horzLines: { color: "#e4e4e7" },
      },
      rightPriceScale: { borderColor: "#e4e4e7", visible: !hidden },
      timeScale: { borderColor: "#e4e4e7" },
      localization: {
        priceFormatter: (price: number) => (hidden ? "••••" : usd(price, 2)),
      },
    });
    const lines = {
      portfolio: curve.map((point) => ({ time: point.date, value: point.value })),
      QQQ: qqq.map((point) => ({ time: point.date, value: point.value })),
      SPY: spy.map((point) => ({ time: point.date, value: point.value })),
    };
    for (const series of SERIES) {
      const row = chart.addSeries(LineSeries, {
        color: series.color,
        lineWidth: series.width,
        title: series.title,
        lastValueVisible: !hidden,
        priceLineVisible: !hidden,
        autoscaleInfoProvider: padScale,
      });
      const data = unique(lines[series.key]);
      if (data.length) row.setData(data);
    }
    chart.timeScale().fitContent();
    return () => {
      chart.remove();
    };
  }, [curve, qqq, spy, hidden]);

  return (
    <section className="card flex min-h-[280px] flex-col">
      <header className="flex items-center justify-between border-b border-zinc-200 px-3 py-2 text-[10px] tracking-[0.16em] text-zinc-500 uppercase">
        Portfolio vs QQQ vs S&P 500
        <span className="tracking-normal text-zinc-600 normal-case">
          {synthetic
            ? "Synthetic demo · fictional portfolio and benchmark prices"
            : "Estimated starting capital · QQQ and SPY use Yahoo Finance daily prices"}
        </span>
      </header>
      <div className="flex gap-5 px-3 pt-1 text-[11px]">
        {SERIES.map((series) => <span key={series.key} style={{ color: series.color }}>{series.title}</span>)}
      </div>
      {curve.length === 0 ? (
        <p className="p-3 text-xs text-zinc-500">
          The comparison needs all-time realized profit on the saved book.
        </p>
      ) : (
        <div ref={host} className="min-h-[240px] flex-1" />
      )}
    </section>
  );
}

function padScale(original: () => { priceRange: { minValue: number; maxValue: number } | null } | null) {
  const res = original();
  if (res?.priceRange == null) return res;
  const span = res.priceRange.maxValue - res.priceRange.minValue;
  const level = Math.max(Math.abs(res.priceRange.maxValue), Math.abs(res.priceRange.minValue));
  if (span > level * 1e-6) return res;
  const padding = level * 0.08;
  return {
    priceRange: {
      minValue: res.priceRange.minValue - padding,
      maxValue: res.priceRange.maxValue + padding,
    },
  };
}

function unique(rows: { time: string; value: number }[]) {
  const seen = new Map<string, number>();
  for (const row of rows) seen.set(row.time, row.value);
  return [...seen.entries()]
    .sort(([left], [right]) => left.localeCompare(right))
    .map(([time, value]) => ({ time, value }));
}
