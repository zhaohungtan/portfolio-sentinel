"use client";

import { useEffect, useRef, useState } from "react";
import { Money } from "@/components/privacy";
import { pct } from "@/lib/format";
import type { Dashboard } from "@/lib/types";

type Tile = Dashboard["heatmap"][number] & { members?: Dashboard["heatmap"] };

type Box = { x: number; y: number; w: number; h: number };
type Node = Tile & { area: number };

function worst(row: Node[], length: number) {
  if (!row.length || length <= 0) return Infinity;
  const areas = row.map((item) => item.area);
  const sum = areas.reduce((total, area) => total + area, 0);
  const max = Math.max(...areas);
  const min = Math.min(...areas);
  const length2 = length * length;
  const sum2 = sum * sum;
  return Math.max((length2 * max) / sum2, sum2 / (length2 * min));
}

function place(row: Node[], box: Box): { placed: (Box & { tile: Tile })[]; rest: Box } {
  const sum = row.reduce((total, item) => total + item.area, 0);
  const placed: (Box & { tile: Tile })[] = [];
  if (box.w >= box.h) {
    const strip = box.h > 0 ? sum / box.h : 0;
    let y = box.y;
    for (const item of row) {
      const h = strip > 0 ? item.area / strip : 0;
      placed.push({ tile: item, x: box.x, y, w: strip, h });
      y += h;
    }
    return { placed, rest: { x: box.x + strip, y: box.y, w: Math.max(0, box.w - strip), h: box.h } };
  }
  const strip = box.w > 0 ? sum / box.w : 0;
  let x = box.x;
  for (const item of row) {
    const w = strip > 0 ? item.area / strip : 0;
    placed.push({ tile: item, x, y: box.y, w, h: strip });
    x += w;
  }
  return { placed, rest: { x: box.x, y: box.y + strip, w: box.w, h: Math.max(0, box.h - strip) } };
}

function squarify(items: Node[], row: Node[], box: Box, out: (Box & { tile: Tile })[]) {
  if (!items.length) {
    if (row.length) out.push(...place(row, box).placed);
    return;
  }
  const [head, ...tail] = items;
  const length = Math.min(box.w, box.h);
  if (!row.length || worst(row, length) >= worst([...row, head], length)) {
    squarify(tail, [...row, head], box, out);
    return;
  }
  const next = place(row, box);
  out.push(...next.placed);
  squarify(items, [], next.rest, out);
}

function mix(from: string, to: string, amount: number) {
  const parse = (hex: string) => [
    parseInt(hex.slice(1, 3), 16),
    parseInt(hex.slice(3, 5), 16),
    parseInt(hex.slice(5, 7), 16),
  ];
  const [ar, ag, ab] = parse(from);
  const [br, bg, bb] = parse(to);
  const channel = (a: number, b: number) => Math.round(a + (b - a) * amount);
  return `rgb(${channel(ar, br)} ${channel(ag, bg)} ${channel(ab, bb)})`;
}

function tilePaint(value: number | null) {
  if (value == null) return { background: "#d4d4d8", color: "#18181b" };
  const strength = Math.min(1, Math.abs(value) / 0.5);
  if (value >= 0) {
    return {
      background: mix("#bbf7d0", "#047857", 0.25 + strength * 0.75),
      color: strength > 0.45 ? "#ffffff" : "#052e16",
    };
  }
  return {
    background: mix("#fecdd3", "#be123c", 0.25 + strength * 0.75),
    color: strength > 0.45 ? "#ffffff" : "#4c0519",
  };
}

function layout(tiles: Tile[], width: number, height: number) {
  const total = tiles.reduce((sum, tile) => sum + Math.max(tile.market_value, 0), 0);
  if (total <= 0 || width <= 0 || height <= 0) return [];
  const nodes: Node[] = tiles
    .filter((tile) => tile.market_value > 0)
    .sort((a, b) => b.market_value - a.market_value)
    .map((tile) => ({ ...tile, area: (tile.market_value / total) * width * height }));
  const out: (Box & { tile: Tile })[] = [];
  squarify(nodes, [], { x: 0, y: 0, w: width, h: height }, out);
  return out;
}

export function HeatMap({
  rows,
  netEquity,
  grossHoldings,
}: {
  rows: Dashboard["heatmap"];
  netEquity: number;
  grossHoldings: number;
}) {
  const frame = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ w: 0, h: 0 });
  const [hover, setHover] = useState<string | null>(null);
  const gross = grossHoldings || rows.reduce((sum, row) => sum + (row.market_value || 0), 0);
  const net = netEquity || gross;

  useEffect(() => {
    const node = frame.current;
    if (!node) return;
    const measure = () => setSize({ w: node.clientWidth, h: node.clientHeight });
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(node);
    return () => observer.disconnect();
  }, []);

  if (!rows.length) {
    return <div className="flex h-[380px] items-center border border-zinc-200 bg-white px-4 text-sm text-zinc-500">No positions</div>;
  }

  const main = rows.filter((row) => gross <= 0 || row.market_value / gross >= 0.01);
  const tiny = rows.filter((row) => gross > 0 && row.market_value / gross < 0.01);
  const tiles: Tile[] = [...main];
  if (tiny.length) {
    const value = tiny.reduce((sum, row) => sum + row.market_value, 0);
    const weighted = tiny.reduce((sum, row) => sum + row.market_value * (row.unrealized_pct ?? 0), 0);
    tiles.push({
      ticker: "Other",
      market_value: value,
      unrealized_pnl: tiny.reduce((sum, row) => sum + (row.unrealized_pnl ?? 0), 0),
      unrealized_pct: value ? weighted / value : null,
      members: tiny,
    });
  }
  const gap = 4;
  const rects = layout(tiles, size.w, size.h).map((rect) => ({
    ...rect,
    x: rect.x + gap / 2,
    y: rect.y + gap / 2,
    w: Math.max(0, rect.w - gap),
    h: Math.max(0, rect.h - gap),
  }));
  const active = rects.find((rect) => rect.tile.ticker === hover);

  return (
    <div className="border border-zinc-200 bg-white p-3">
      <div ref={frame} className="relative h-[380px] overflow-hidden bg-white">
        {rects.map((rect) => {
          const paint = tilePaint(rect.tile.unrealized_pct);
          const weight = gross ? (rect.tile.market_value / gross) * 100 : 0;
          const large = rect.w > 212 && rect.h > 120;
          const medium = rect.w > 96 && rect.h > 72;
          return (
            <div
              key={rect.tile.ticker}
              className="absolute flex flex-col justify-center overflow-hidden px-3"
              style={{ left: rect.x, top: rect.y, width: rect.w, height: rect.h, background: paint.background, color: paint.color }}
              onMouseEnter={() => setHover(rect.tile.ticker)}
              onMouseLeave={() => setHover(null)}
            >
              <div className={`truncate font-semibold tracking-wide ${large ? "text-4xl" : medium ? "text-xl" : "text-xs"}`}>
                {rect.tile.ticker}
              </div>
              <div className={`num mt-1 ${large ? "text-3xl" : medium ? "text-lg" : "text-[11px]"}`}>
                {weight > 0 && weight < 1 ? weight.toFixed(2) : weight.toFixed(1)}%
              </div>
              <div className={`num mt-1 truncate ${large ? "text-sm" : "text-[10px]"}`}>{pct(rect.tile.unrealized_pct)}</div>
            </div>
          );
        })}
        {active ? (
          <div
            className="pointer-events-none absolute z-20 w-max max-w-[240px] border border-black bg-white px-3 py-2 text-xs text-black shadow-lg"
            style={{
              left: Math.min(active.x + 8, Math.max(0, size.w - 220)),
              top: Math.max(8, active.y + active.h - 72),
            }}
          >
            <div className="font-semibold">{active.tile.ticker}</div>
            <div className="num">
              {gross ? ((active.tile.market_value / gross) * 100).toFixed(1) : "0.0"}% of portfolio ·{" "}
              {net ? ((active.tile.market_value / net) * 100).toFixed(1) : "0.0"}% of net
            </div>
            <div className="num">
              <Money value={active.tile.market_value} /> · {pct(active.tile.unrealized_pct)}
            </div>
            {active.tile.members?.length ? (
              <div className="mt-1 text-[10px] text-zinc-500">{active.tile.members.map((item) => item.ticker).join(" ")}</div>
            ) : null}
          </div>
        ) : null}
      </div>
    </div>
  );
}
