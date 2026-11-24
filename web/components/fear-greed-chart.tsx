"use client";

import { useEffect, useRef } from "react";
import { ColorType, createChart, LineSeries, LineStyle, type IChartApi } from "lightweight-charts";
import type { Dashboard } from "@/lib/types";

const GUIDES = [
  { price: 25, title: "Extreme fear" },
  { price: 45, title: "Fear" },
  { price: 55, title: "Neutral" },
  { price: 75, title: "Greed" },
];

export function FearGreedChart({ fear }: { fear: Dashboard["fear_greed"] }) {
  const host = useRef<HTMLDivElement>(null);
  const series = fear?.series ?? [];
  const rating = fear?.rating ?? "";
  const color = tone(rating);

  useEffect(() => {
    const element = host.current;
    if (!element || series.length === 0) return;
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
      rightPriceScale: { borderColor: "#e4e4e7" },
      timeScale: { borderColor: "#e4e4e7" },
      localization: {
        priceFormatter: (price: number) => price.toFixed(0),
      },
    });
    const row = chart.addSeries(LineSeries, {
      color,
      lineWidth: 2,
      title: "Index",
      autoscaleInfoProvider: () => ({ priceRange: { minValue: 0, maxValue: 100 } }),
    });
    const seen = new Map<string, number>();
    for (const point of series) seen.set(point.date, point.score);
    row.setData(
      [...seen.entries()]
        .sort(([left], [right]) => left.localeCompare(right))
        .map(([time, value]) => ({ time, value })),
    );
    for (const guide of GUIDES) {
      row.createPriceLine({
        price: guide.price,
        color: "#a1a1aa",
        lineWidth: 1,
        lineStyle: LineStyle.Dashed,
        axisLabelVisible: false,
        title: guide.title,
      });
    }
    chart.timeScale().fitContent();
    return () => {
      chart.remove();
    };
  }, [series, color]);

  return (
    <section className="card flex min-h-[280px] flex-col">
      <header className="flex items-center justify-between border-b border-zinc-200 px-3 py-2 text-[10px] tracking-[0.16em] text-zinc-500 uppercase">
        Fear and greed
        <span className="num tracking-normal normal-case" style={{ color }}>
          {fear?.score == null ? "—" : `${fear.score.toFixed(0)} · ${label(rating)}`}
        </span>
      </header>
      {series.length === 0 ? (
        <p className="p-3 text-xs text-zinc-500">The market index is not available yet.</p>
      ) : (
        <div ref={host} className="min-h-[240px] flex-1" />
      )}
    </section>
  );
}

function tone(rating: string) {
  if (rating === "extreme fear" || rating === "fear") return "#be123c";
  if (rating === "greed" || rating === "extreme greed") return "#047857";
  return "#b45309";
}

function label(rating: string) {
  if (!rating) return "Neutral";
  return rating.replace(/\b\w/g, (letter) => letter.toUpperCase());
}
