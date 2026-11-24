export type Catalyst = {
  date: string;
  time_et: string | null;
  name: string;
  kind: "macro" | "company";
  ticker: string | null;
  held_ticker: string | null;
  days_remaining: number;
  exposure_usd: number;
  weight: number | null;
  highlighted: boolean;
  implied_move_pct: number | null;
  implied_move_source: string | null;
};

export type NewsItem = {
  ticker: string;
  held_tickers: string[];
  title: string;
  publisher?: string | null;
  url?: string | null;
  published_at: string;
  polarity: "POSITIVE" | "NEGATIVE" | "NEUTRAL";
  sentiment: number;
  scope: "MACRO" | "COMPANY";
  exposure_usd: number;
  windows: string[];
};

export type PositionRow = {
  ticker: string;
  name?: string | null;
  shares?: number | null;
  news_tickers?: string[];
  leverage?: number;
  unrealized_pnl?: number | null;
  current_price?: number;
  avg_cost?: number | null;
  market_value?: number;
  daily_variance_drag?: number | null;
  breakeven_underlying_30d?: number | null;
  breakeven_underlying_60d?: number | null;
  stop_limit_trigger?: number | null;
  cost_basis?: number | null;
  breakeven_gain_usd?: number | null;
  equity_if_breakeven?: number | null;
  clears_margin?: boolean;
  signal?: string;
  vol_capped?: boolean;
  underlying_symbol?: string | null;
  underlying_price?: number | null;
  underlying_target_30d?: number | null;
  atr_14?: number | null;
};

export type MarginScenario = {
  id: string;
  label: string;
  buffer_usd: number;
  buffer_pct: number;
  daily_gold: number;
  stressed_5d: number;
  stressed_21d: number;
  margin_used: number;
  net_equity: number;
  gross_holdings: number;
};

export type Dashboard = {
  source: string;
  as_of: string;
  sigma_source: string;
  broker_source?: string | null;
  broker_net_equity?: number | null;
  market_quotes?: {
    source: string;
    oldest_as_of: string | null;
    latest_as_of: string | null;
    updated: string[];
    unchanged: string[];
  } | null;
  warnings?: string[];
  capital?: {
    net_equity: number;
    gross_holdings: number;
    margin_debt: number;
    look_through_usd: number;
    korea_overnight_usd: number;
  };
  korea?: {
    combined_usd?: number | null;
    samsung_usd?: number | null;
    sk_hynix_usd?: number | null;
  };
  margin: {
    probabilities?: Record<string, { baseline?: number; stressed?: number }>;
    stressed_static_buffer_usd?: number | null;
    stressed_static_buffer_pct?: number | null;
    drops?: {
      baseline_drop_usd?: number | null;
      baseline_drop_pct?: number | null;
      stressed_drop_usd?: number | null;
      stressed_drop_pct?: number | null;
      stressed_static_buffer_usd?: number | null;
      stressed_static_buffer_pct?: number | null;
    };
    pnl_percentiles_21d: { percentile: number; pnl_usd: number }[];
    margin_used: number;
    equity_value: number;
    daily_gold?: number;
    scenarios?: MarginScenario[];
  };
  performance: {
    track_record: string;
    twr: number | null;
    sharpe: number | null;
    win_rate: number | null;
    alpha_smh: number | null;
    alpha_qqq?: number | null;
    alpha_spy?: number | null;
    benchmark_twr?: Record<string, number | null>;
    point_in_time: boolean;
    unrealized_pnl: number | null;
    daily_gold_carry: number;
    daily_decay_drag: number;
    cumulative_drag: number;
    equity_curve: { date: string; net_equity: number; high_water: number }[];
    benchmark_curves?: Record<string, { date: string; value: number }[]>;
    same_cash?: {
      money_in: number;
      net_equity: number;
      change_usd: number;
      change_pct: number | null;
      first_activity_date: string;
      portfolio: { date: string; value: number }[];
      benchmarks: Record<string, { date: string; value: number }[]>;
      qqq_now: number | null;
      spy_now: number | null;
      alpha_qqq: number | null;
      alpha_spy: number | null;
    } | null;
  };
  fear_greed?: {
    score: number;
    rating: string;
    series: { date: string; score: number; rating: string }[];
  } | null;
  next_catalyst: Catalyst | null;
  radar: Catalyst[];
  sentiment: Record<string, number | null>;
  heatmap: {
    ticker: string;
    market_value: number;
    unrealized_pnl: number | null;
    unrealized_pct: number | null;
  }[];
  positions: PositionRow[];
  news: NewsItem[];
};
