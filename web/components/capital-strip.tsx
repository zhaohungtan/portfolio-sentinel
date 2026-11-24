"use client";

import { Money } from "@/components/privacy";
import type { Dashboard } from "@/lib/types";

export function CapitalStrip({ data }: { data: Dashboard }) {
  const capital = data.capital;
  const korea = data.korea?.combined_usd ?? capital?.korea_overnight_usd ?? 0;
  const cells = [
    ["Robinhood net equity", data.broker_net_equity ?? capital?.net_equity ?? 0],
    ...(data.market_quotes?.updated.length && data.broker_net_equity != null
      ? [["Estimated net equity", capital?.net_equity ?? 0] as const]
      : []),
    ["Gross holdings", capital?.gross_holdings ?? 0],
    ["Margin debt", capital?.margin_debt ?? 0],
    ["1x look-through", capital?.look_through_usd ?? 0],
    ["Korea overnight", korea],
  ] as const;
  return (
    <section className="grid grid-cols-2 border border-zinc-200 bg-white sm:grid-flow-col sm:auto-cols-fr">
      {cells.map(([label, value]) => (
        <div key={label} className="border-zinc-200 px-4 py-4 sm:border-l sm:first:border-l-0">
          <div className="text-[11px] font-medium tracking-[0.14em] text-zinc-500 uppercase">{label}</div>
          <div className="num mt-1 text-2xl font-semibold tracking-tight text-black sm:text-3xl">
            <Money value={value} />
          </div>
        </div>
      ))}
    </section>
  );
}
