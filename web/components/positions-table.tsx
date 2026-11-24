"use client";

import { useMemo, useState } from "react";
import { flexRender } from "@tanstack/react-table";
import { getCoreRowModel, legacyCreateColumnHelper, useLegacyTable } from "@tanstack/react-table/legacy";
import { Money, usePrivacy } from "@/components/privacy";
import { Badge } from "@/components/ui/badge";
import { pct, usd } from "@/lib/format";
import type { PositionRow } from "@/lib/types";

const helper = legacyCreateColumnHelper<PositionRow>();

type SortKey =
  | "ticker"
  | "weight"
  | "shares"
  | "value"
  | "breakeven"
  | "price"
  | "leverage"
  | "basket"
  | "drag"
  | "be30"
  | "be60"
  | "signal"
  | "stop";

const HEADERS: { id: SortKey; label: string; align?: "right" }[] = [
  { id: "ticker", label: "Stock" },
  { id: "weight", label: "% of portfolio", align: "right" },
  { id: "shares", label: "Shares owned", align: "right" },
  { id: "value", label: "Value owned", align: "right" },
  { id: "breakeven", label: "Breakeven P/L", align: "right" },
  { id: "price", label: "Price / avg", align: "right" },
  { id: "leverage", label: "Lev", align: "right" },
  { id: "basket", label: "Underlying" },
  { id: "drag", label: "Drag/day", align: "right" },
  { id: "be30", label: "30D BE", align: "right" },
  { id: "be60", label: "60D BE", align: "right" },
  { id: "signal", label: "Signal" },
  { id: "stop", label: "1.5x ATR", align: "right" },
];

function num(value: number | null | undefined) {
  return value == null || Number.isNaN(value) ? null : value;
}

function sharesLabel(value: number | null | undefined) {
  const count = num(value);
  if (count == null) return "—";
  const digits = Math.abs(count) >= 100 ? 0 : Math.abs(count) >= 1 ? 2 : 4;
  return count.toLocaleString("en-US", { maximumFractionDigits: digits });
}

function Shares({ value }: { value: number | null | undefined }) {
  const { hidden } = usePrivacy();
  return <span className="num text-black">{hidden ? "••••" : sharesLabel(value)}</span>;
}

function sortValue(row: PositionRow, key: SortKey, gross: number) {
  switch (key) {
    case "ticker":
      return row.ticker;
    case "weight":
      return gross > 0 ? (row.market_value ?? 0) / gross : 0;
    case "shares":
      return row.shares ?? 0;
    case "value":
      return row.market_value ?? 0;
    case "breakeven":
      return row.unrealized_pnl ?? 0;
    case "price":
      return row.current_price ?? 0;
    case "leverage":
      return row.leverage ?? 0;
    case "basket":
      return (row.news_tickers || []).join(" ");
    case "drag":
      return row.daily_variance_drag ?? 0;
    case "be30":
      return row.breakeven_underlying_30d ?? 0;
    case "be60":
      return row.breakeven_underlying_60d ?? 0;
    case "signal":
      return row.signal ?? "";
    case "stop":
      return row.stop_limit_trigger ?? 0;
  }
}

export function PositionsTable({ rows, grossHoldings }: { rows: PositionRow[]; grossHoldings: number }) {
  const [selected, setSelected] = useState<PositionRow | null>(null);
  const [sort, setSort] = useState<{ id: SortKey; desc: boolean }>({ id: "weight", desc: true });
  const gross = grossHoldings || rows.reduce((sum, row) => sum + (row.market_value || 0), 0);
  const ordered = useMemo(() => {
    const copy = [...rows];
    copy.sort((a, b) => {
      const left = sortValue(a, sort.id, gross);
      const right = sortValue(b, sort.id, gross);
      const result = typeof left === "string" || typeof right === "string" ? String(left).localeCompare(String(right)) : left - right;
      return sort.desc ? -result : result;
    });
    return copy;
  }, [rows, sort, gross]);

  const columns = useMemo(
    () => [
      helper.display({
        id: "ticker",
        header: "Stock",
        cell: (info) => (
          <div>
            <div className="font-semibold text-black">{info.row.original.ticker}</div>
            {info.row.original.name ? <div className="text-[11px] text-zinc-500">{info.row.original.name}</div> : null}
          </div>
        ),
      }),
      helper.display({
        id: "weight",
        header: "% of portfolio",
        cell: (info) => {
          const weight = gross > 0 ? ((info.row.original.market_value ?? 0) / gross) * 100 : 0;
          return (
            <div className="ml-auto inline-block w-24 text-left">
              <div className="num text-black">{weight.toFixed(2)}%</div>
              <div className="mt-1 h-1 bg-zinc-200">
                <div className="h-full bg-black" style={{ width: `${Math.min(weight, 100)}%` }} />
              </div>
            </div>
          );
        },
      }),
      helper.display({
        id: "shares",
        header: "Shares owned",
        cell: (info) => <Shares value={info.row.original.shares} />,
      }),
      helper.display({
        id: "value",
        header: "Value owned",
        cell: (info) => (
          <span className="num text-black">
            <Money value={info.row.original.market_value} />
          </span>
        ),
      }),
      helper.display({
        id: "breakeven",
        header: "Breakeven P/L",
        cell: (info) => <BreakEven row={info.row.original} />,
      }),
      helper.display({
        id: "price",
        header: "Price / avg",
        cell: (info) => (
          <span className="num text-black">
            <Money value={info.row.original.current_price} digits={2} />
            <span className="text-zinc-400"> / </span>
            <Money value={info.row.original.avg_cost} digits={2} />
          </span>
        ),
      }),
      helper.display({
        id: "leverage",
        header: "Lev",
        cell: (info) => <span className="num">{info.row.original.leverage ? `${info.row.original.leverage}x` : "—"}</span>,
      }),
      helper.display({
        id: "basket",
        header: "Underlying",
        cell: (info) => <Basket tickers={info.row.original.news_tickers || []} />,
      }),
      helper.display({
        id: "drag",
        header: "Drag/day",
        cell: (info) => <span className="num">{pct(info.row.original.daily_variance_drag, 3)}</span>,
      }),
      helper.display({
        id: "be30",
        header: "30D BE",
        cell: (info) => <span className="num">{pct(info.row.original.breakeven_underlying_30d)}</span>,
      }),
      helper.display({
        id: "be60",
        header: "60D BE",
        cell: (info) => <span className="num">{pct(info.row.original.breakeven_underlying_60d)}</span>,
      }),
      helper.display({
        id: "signal",
        header: "Signal",
        cell: (info) => <Signal name={info.row.original.signal} />,
      }),
      helper.display({
        id: "stop",
        header: "1.5x ATR",
        cell: (info) => (
          <span className="flex items-center justify-end gap-1">
            <Money value={info.row.original.stop_limit_trigger} digits={2} />
            {info.row.original.vol_capped ? <Badge tone="warn">Vol cap</Badge> : null}
          </span>
        ),
      }),
    ],
    [gross],
  );
  const table = useLegacyTable({ data: ordered, columns, getCoreRowModel: getCoreRowModel() });

  function toggle(id: SortKey) {
    setSort((current) => (current.id === id ? { id, desc: !current.desc } : { id, desc: id === "ticker" || id === "basket" || id === "signal" ? false : true }));
  }

  return (
    <section className="flex flex-col border border-zinc-200 bg-white text-black">
      <header className="border-b border-zinc-200 px-4 py-3">
        <h2 className="text-lg font-semibold tracking-tight">Holdings</h2>
      </header>
      <div className="overflow-auto">
        <table className="w-full min-w-[1100px] border-collapse text-left text-[13px]">
          <thead className="text-[11px] tracking-wide text-zinc-500 uppercase">
            {table.getHeaderGroups().map((group) => (
              <tr key={group.id} className="border-b border-zinc-200">
                {group.headers.map((header) => {
                  const meta = HEADERS.find((item) => item.id === header.id);
                  const active = sort.id === header.id;
                  return (
                    <th key={header.id} className={`px-3 py-2 font-medium ${meta?.align === "right" ? "text-right" : "text-left"}`}>
                      <button
                        type="button"
                        className="inline-flex items-center gap-1 hover:text-black"
                        onClick={() => toggle(header.id as SortKey)}
                      >
                        {flexRender(header.column.columnDef.header, header.getContext())}
                        <span className="num text-[10px] text-zinc-400">{active ? (sort.desc ? "↓" : "↑") : "↕"}</span>
                      </button>
                    </th>
                  );
                })}
              </tr>
            ))}
          </thead>
          <tbody>
            {table.getRowModel().rows.map((row) => (
              <tr
                key={row.id}
                className="cursor-pointer border-b border-zinc-100 hover:bg-zinc-50"
                onClick={() => setSelected(row.original)}
              >
                {row.getVisibleCells().map((cell) => {
                  const meta = HEADERS.find((item) => item.id === cell.column.id);
                  return (
                    <td key={cell.id} className={`px-3 py-3 text-zinc-800 ${meta?.align === "right" ? "text-right" : "text-left"}`}>
                      {flexRender(cell.column.columnDef.cell, cell.getContext())}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {selected ? <PositionDrawer row={selected} onClose={() => setSelected(null)} /> : null}
    </section>
  );
}

const DISPLAY_NAMES: Record<string, string> = {
  MU: "MU",
  "005930.KS": "Samsung",
  "000660.KS": "SK hynix",
};

function BreakEven({ row }: { row: PositionRow }) {
  const pnl = row.unrealized_pnl;
  const cost = row.cost_basis;
  if (pnl == null) return <span className="text-zinc-400">—</span>;
  const ratio = cost ? pnl / cost : null;
  const down = pnl < 0;
  return (
    <span className="inline-flex flex-wrap items-center justify-end gap-1">
      <span className={`num ${down ? "text-[#be123c]" : "text-[#047857]"}`}>
        <Money value={pnl} />
        {ratio != null ? <span> ({pct(ratio)})</span> : null}
      </span>
      {row.clears_margin ? <Badge tone="good">Clears margin</Badge> : null}
    </span>
  );
}

function Signal({ name }: { name?: string }) {
  if (!name) return <span className="text-zinc-400">—</span>;
  const tone = name === "NEAR BE" ? "good" : name === "HIGH DECAY" ? "bad" : name === "CORE DRIVER" ? "warn" : "neutral";
  return <Badge tone={tone}>{name}</Badge>;
}

function PositionDrawer({ row, onClose }: { row: PositionRow; onClose: () => void }) {
  const target =
    row.underlying_symbol && row.underlying_target_30d != null
      ? `${row.underlying_symbol} ${usd(row.underlying_target_30d, 2)}`
      : null;
  return (
    <aside className="fixed inset-y-0 right-0 z-30 flex w-[320px] flex-col border-l border-zinc-200 bg-white text-black shadow-2xl">
      <header className="flex items-center justify-between border-b border-zinc-200 px-4 py-3">
        <div>
          <div className="text-lg font-semibold">{row.ticker}</div>
          <div className="text-[11px] tracking-wide text-zinc-500 uppercase">{row.name ?? row.signal ?? "Position"}</div>
        </div>
        <button onClick={onClose} className="text-sm text-zinc-500">
          Close
        </button>
      </header>
      <div className="flex flex-col gap-3 px-4 py-4 text-[13px] text-zinc-700">
        <p>
          Shares owned <Shares value={row.shares} />
        </p>
        <p>
          Value owned{" "}
          <span className="num text-black">
            <Money value={row.market_value} />
          </span>
        </p>
        <p>
          30-day underlying target <span className="num text-black">{target ?? pct(row.breakeven_underlying_30d)}</span>
        </p>
        <p>
          60-day rally <span className="num text-black">{pct(row.breakeven_underlying_60d)}</span>
        </p>
        <p>
          If this name returns to cost, net equity is{" "}
          <span className="num text-black">
            <Money value={row.equity_if_breakeven} />
          </span>
          . The dollar gap ignores variance drag. The target price includes the 30-day drag.
        </p>
        <p>
          1.5x ATR stop{" "}
          <span className="num text-black">
            <Money value={row.stop_limit_trigger} digits={2} />
          </span>
          {row.vol_capped ? <Badge tone="warn">Vol cap</Badge> : null}
        </p>
      </div>
    </aside>
  );
}

function Basket({ tickers }: { tickers: string[] }) {
  if (!tickers.length) return <span className="text-zinc-400">—</span>;
  const labels = tickers.map((ticker) => DISPLAY_NAMES[ticker] ?? ticker);
  const shown = labels.slice(0, 3);
  const extra = labels.length - shown.length;
  return (
    <span className="flex flex-wrap items-center gap-1">
      {shown.map((label) => (
        <span key={label} className="border border-zinc-300 px-1 py-0.5 text-[10px] text-zinc-700">
          {label}
        </span>
      ))}
      {extra > 0 ? <span className="text-[10px] text-zinc-500">+{extra}</span> : null}
    </span>
  );
}
