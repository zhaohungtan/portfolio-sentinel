"use client";

import { useEffect, useMemo, useState, type ReactNode } from "react";
import type { NewsItem } from "@/lib/types";

const WINDOWS = ["24H", "72H", "7D"] as const;
const SCOPES = ["All", "Macro", "Company"] as const;
const POLARITY = ["All", "Positive", "Negative"] as const;
const PAGE_SIZE = 6;

export function NewsTape({ items }: { items: NewsItem[] }) {
  const [horizon, setHorizon] = useState<(typeof WINDOWS)[number]>("7D");
  const [scope, setScope] = useState<(typeof SCOPES)[number]>("All");
  const [polarity, setPolarity] = useState<(typeof POLARITY)[number]>("All");
  const [newestFirst, setNewestFirst] = useState(true);
  const [page, setPage] = useState(0);

  const rows = useMemo(() => {
    const filtered = items.filter((item) => {
      if (!item.windows?.includes(horizon)) return false;
      if (scope === "Macro" && item.scope !== "MACRO") return false;
      if (scope === "Company" && item.scope !== "COMPANY") return false;
      if (polarity === "Positive" && item.polarity !== "POSITIVE") return false;
      if (polarity === "Negative" && item.polarity !== "NEGATIVE") return false;
      return true;
    });
    filtered.sort((a, b) => (newestFirst ? b.published_at.localeCompare(a.published_at) : a.published_at.localeCompare(b.published_at)));
    return filtered;
  }, [items, horizon, scope, polarity, newestFirst]);

  useEffect(() => {
    setPage(0);
  }, [items]);

  const pages = Math.max(1, Math.ceil(rows.length / PAGE_SIZE));
  const current = Math.min(page, pages - 1);
  const visible = rows.slice(current * PAGE_SIZE, current * PAGE_SIZE + PAGE_SIZE);
  const start = rows.length ? current * PAGE_SIZE + 1 : 0;
  const end = Math.min(rows.length, (current + 1) * PAGE_SIZE);

  return (
    <section className="card flex flex-col">
      <header className="flex flex-wrap items-center gap-x-3 gap-y-2 border-b border-zinc-200 px-4 py-3">
        <h2 className="text-sm font-semibold text-zinc-900">News</h2>
        <span className="num text-[11px] text-zinc-500">
          {rows.length} of {items.length} · {horizon}
          {scope !== "All" ? ` · ${scope}` : ""}
          {polarity !== "All" ? ` · ${polarity}` : ""}
        </span>
        <FilterGroup label="Time">
          {WINDOWS.map((item) => (
            <Pill
              key={item}
              active={horizon === item}
              onClick={() => {
                setHorizon(item);
                setPage(0);
              }}
            >
              {item}
            </Pill>
          ))}
        </FilterGroup>
        <FilterGroup label="Scope">
          {SCOPES.map((item) => (
            <Pill
              key={`scope-${item}`}
              active={scope === item}
              onClick={() => {
                setScope(item);
                setPage(0);
              }}
            >
              {item}
            </Pill>
          ))}
        </FilterGroup>
        <FilterGroup label="Polarity">
          {POLARITY.map((item) => (
            <Pill
              key={`polarity-${item}`}
              active={polarity === item}
              onClick={() => {
                setPolarity(item);
                setPage(0);
              }}
            >
              {item}
            </Pill>
          ))}
        </FilterGroup>
        <button
          type="button"
          onClick={() => {
            setNewestFirst((value) => !value);
            setPage(0);
          }}
          className="ml-auto border border-zinc-200 px-1.5 py-0.5 text-[10px] tracking-wide text-zinc-700 uppercase"
        >
          {newestFirst ? "Newest" : "Oldest"}
        </button>
      </header>
      {visible.length === 0 ? (
        <p className="px-4 py-6 text-sm text-zinc-500">No relevant headlines in this window.</p>
      ) : (
        <ul>
          {visible.map((item) => (
            <li key={`${item.ticker}-${item.published_at}-${item.title}`} className="border-b border-zinc-100 last:border-b-0">
              <Story item={item} />
            </li>
          ))}
        </ul>
      )}
      <footer className="flex items-center justify-between border-t border-zinc-200 px-4 py-2 text-[11px] text-zinc-500">
        <span className="num">
          {start}–{end} of {rows.length}
        </span>
        <span className="flex items-center gap-1">
          <button
            type="button"
            disabled={current === 0}
            onClick={() => setPage((value) => Math.max(0, value - 1))}
            className="border border-zinc-200 px-2 py-1 text-zinc-700 disabled:opacity-40"
          >
            Prev
          </button>
          <span className="num px-1">
            {current + 1}/{pages}
          </span>
          <button
            type="button"
            disabled={current >= pages - 1}
            onClick={() => setPage((value) => Math.min(pages - 1, value + 1))}
            className="border border-zinc-200 px-2 py-1 text-zinc-700 disabled:opacity-40"
          >
            Next
          </button>
        </span>
      </footer>
    </section>
  );
}

function Story({ item }: { item: NewsItem }) {
  const tone = item.polarity === "POSITIVE" ? "text-[#047857]" : item.polarity === "NEGATIVE" ? "text-[#be123c]" : "text-zinc-400";
  const mark = item.polarity === "POSITIVE" ? "+" : item.polarity === "NEGATIVE" ? "−" : "·";
  const body = (
    <>
      <span className={`num w-4 text-sm ${tone}`}>{mark}</span>
      <span className="min-w-0">
        <span className="block text-sm leading-5 text-zinc-900">{item.title}</span>
        <span className="mt-0.5 block text-[11px] text-zinc-500">
          {item.held_tickers?.length ? item.held_tickers.join(", ") : item.ticker}
          {item.publisher ? ` · ${item.publisher}` : ""}
          {" · "}
          {item.published_at.replace("T", " ").slice(0, 16)}
        </span>
      </span>
    </>
  );
  if (!item.url) {
    return <div className="flex items-start gap-3 px-4 py-3">{body}</div>;
  }
  return (
    <a href={item.url} target="_blank" rel="noreferrer" className="flex items-start gap-3 px-4 py-3 hover:bg-zinc-50">
      {body}
    </a>
  );
}

function FilterGroup({ label, children }: { label: string; children: ReactNode }) {
  return (
    <span className="flex items-center gap-1">
      <span className="text-[10px] text-zinc-500">{label}</span>
      {children}
    </span>
  );
}

function Pill({
  active,
  children,
  onClick,
}: {
  active: boolean;
  children: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`border px-2 py-1 text-[10px] tracking-wide uppercase ${
        active ? "border-zinc-900 bg-zinc-900 text-white" : "border-zinc-300 bg-white text-zinc-600"
      }`}
    >
      {children}
    </button>
  );
}
