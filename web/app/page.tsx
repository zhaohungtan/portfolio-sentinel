"use client";

import { useCallback, useEffect, useState } from "react";
import { CapitalStrip } from "@/components/capital-strip";
import { CatalystRadar } from "@/components/catalyst-radar";
import { EquityChart } from "@/components/equity-chart";
import { FearGreedChart } from "@/components/fear-greed-chart";
import { HeatMap } from "@/components/heat-map";
import { MorningCards } from "@/components/morning-cards";
import { NewsTape } from "@/components/news-tape";
import { PositionsTable } from "@/components/positions-table";
import { PrivacyProvider } from "@/components/privacy";
import { StatusBar } from "@/components/status-bar";
import type { Dashboard } from "@/lib/types";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export default function Home() {
  return (
    <PrivacyProvider>
      <Desk />
    </PrivacyProvider>
  );
}

function Desk() {
  const [data, setData] = useState<Dashboard | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    const response = await fetch(`${API}/api/dashboard`, { cache: "no-store" });
    if (!response.ok) throw new Error(`desk ${response.status}`);
    setData((await response.json()) as Dashboard);
  }, []);

  useEffect(() => {
    setBusy(true);
    load().catch((reason: unknown) => {
      setError(reason instanceof Error ? reason.message : "desk unreachable");
    }).finally(() => setBusy(false));
  }, [load]);

  async function syncNews() {
    setBusy(true);
    setError(null);
    try {
      const response = await fetch(`${API}/api/sync-news`, { method: "POST" });
      if (!response.ok) throw new Error(`news ${response.status}`);
      const result = (await response.json()) as Dashboard;
      setData((current) => current ? {
        ...current, news: result.news, sentiment: result.sentiment,
      } : result);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "news sync failed");
    } finally {
      setBusy(false);
    }
  }

  async function refresh() {
    setBusy(true);
    setError(null);
    try {
      const response = await fetch(`${API}/api/sync-robinhood`, { method: "POST", cache: "no-store" });
      if (!response.ok) {
        const result = await response.json().catch(() => null);
        throw new Error(result?.detail ?? `Robinhood sync failed (${response.status})`);
      }
      setData((await response.json()) as Dashboard);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "refresh failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="min-h-screen">
      <StatusBar
        asOf={data?.as_of ?? null}
        source={data?.source ?? null}
        busy={busy}
        onRefresh={refresh}
        onSyncNews={syncNews}
      />
      <div className="flex flex-col gap-2 p-3">
        {error ? (
          <p className="card px-3 py-2 text-xs text-[#be123c]">
            {error}
          </p>
        ) : null}
        {data ? (
          <>
            <p className="px-1 text-xs text-zinc-600" role="status">
              {data.broker_source === "robinhood-mcp" ? "Robinhood synced" : data.source === "live" ? "Saved account snapshot" : "Sample snapshot"}
              {" · "}{new Date(data.as_of).toLocaleString()}
              {data.market_quotes?.latest_as_of ? (
                <> · Yahoo Finance marks through {new Date(data.market_quotes.latest_as_of).toLocaleString()}
                  {" · "}{data.market_quotes.updated.length} updated
                  {data.market_quotes.unchanged.length > 0
                    ? ` · Snapshot marks retained for ${data.market_quotes.unchanged.join(", ")}`
                    : ""}
                </>
              ) : data.market_quotes?.unchanged.length ? " · No newer market quotes available" : ""}
            </p>
            {data.warnings?.map((warning) => (
              <p key={warning} className="px-1 text-xs text-amber-800">{warning}</p>
            ))}
            <CapitalStrip data={data} />
            <HeatMap
              rows={data.heatmap}
              netEquity={data.capital?.net_equity ?? 0}
              grossHoldings={data.capital?.gross_holdings ?? 0}
            />
            <PositionsTable rows={data.positions} grossHoldings={data.capital?.gross_holdings ?? 0} />
            <MorningCards data={data} />
            <div className="grid grid-cols-1 gap-2 xl:grid-cols-[minmax(0,1.85fr)_minmax(0,1fr)]">
              <EquityChart performance={data.performance} />
              <CatalystRadar events={data.radar} />
            </div>
            <FearGreedChart fear={data.fear_greed} />
            <NewsTape items={data.news} />
          </>
        ) : error ? null : (
          <p className="text-xs text-zinc-500">Loading the book…</p>
        )}
      </div>
    </main>
  );
}
