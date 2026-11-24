"""Look-through exposure, leveraged-ETF decay, and ATR stop levels.

Break-even rallies use a constant-drift approximation. They are not a
promise about the path the underlying will take.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping, Sequence

import numpy as np

from src.constants import (
    AI_CLUSTER,
    ATR_MULTIPLE,
    ATR_PERIOD,
    BREAKEVEN_HORIZONS,
    GOLD_INTEREST_FREE_USD,
    GOLD_MARGIN_APR,
    KOREA_HYNIX_KEY,
    KOREA_SAMSUNG_KEY,
    MAINTENANCE_RATE,
    VOL_WINDOW,
)
from src.db import SnapshotRow

MAINTENANCE_NOTE = (
    "Broker payload has no maintenance excess. "
    "maintenance_excess_estimated is net equity minus 25% of long equity "
    "market value and is not a Robinhood margin figure."
)
BREAKEVEN_NOTE = (
    "Constant-drift estimate of the underlying rally required for the "
    "held price to regain average cost. Not a path guarantee."
)


ACTIVE_MIN_MARKET_VALUE = 1.0


def is_active_position(position: Mapping[str, Any]) -> bool:
    """Held shares worth at least $1. Missing shares still count as held.

    Dust and a sold name with shares of zero stay out of risk, news, and
    catalysts. Net equity is computed separately and still includes them.
    """
    shares = position.get("shares")
    if shares is not None and shares != "" and float(shares) <= 0:
        return False
    return float(position.get("market_value") or 0.0) >= ACTIVE_MIN_MARKET_VALUE


def select_primary_account(book: Mapping[str, Any]) -> dict[str, Any]:
    accounts = list(book.get("accounts") or [])
    for account in accounts:
        if account.get("role") == "primary":
            return account
    for account in accounts:
        if (
            account.get("is_default")
            and account.get("account_type") == "individual"
            and not account.get("is_agentic")
        ):
            return account
    raise ValueError("live book has no primary individual account")


def parse_as_of(book: Mapping[str, Any]) -> datetime:
    raw = book.get("as_of")
    if not raw:
        raise ValueError("live book is missing as_of")
    return datetime.fromisoformat(str(raw))


def daily_variance_drag(leverage: float, sigma_daily: float) -> float:
    """Expected daily variance drag of a daily-reset leveraged ETF.

    For leverage L the drag is L*(L-1)/2 * σ². At 2x that is σ². At 1x it is 0.
    """
    if leverage < 1:
        raise ValueError(f"leverage must be at least 1, got {leverage}")
    return (leverage * (leverage - 1.0) / 2.0) * sigma_daily**2


def required_underlying_rally(
    avg_cost: float,
    price: float,
    leverage: float,
    daily_drag: float,
    horizon_days: int,
) -> float:
    """Fraction the underlying must rise so the held ETF can regain avg_cost.

    required = ((avg_cost / price - 1) + daily_drag * T) / leverage
    """
    if price <= 0 or leverage <= 0:
        raise ValueError("price and leverage must be positive")
    if price >= avg_cost:
        return 0.0
    etf_gap = (avg_cost / price) - 1.0
    return (etf_gap + daily_drag * horizon_days) / leverage


def look_through(market_value: float, leverage: float) -> float:
    return market_value * leverage


def gold_carry(cash: float) -> dict[str, float]:
    """Interest on margin above the Robinhood Gold interest-free allowance."""
    margin_used = max(0.0, -float(cash))
    interest_bearing = max(0.0, margin_used - GOLD_INTEREST_FREE_USD)
    annual = interest_bearing * GOLD_MARGIN_APR
    return {
        "margin_used": margin_used,
        "interest_free_allowance": GOLD_INTEREST_FREE_USD,
        "interest_bearing_balance": interest_bearing,
        "apr": GOLD_MARGIN_APR,
        "annual_interest_carry": annual,
        "daily_interest_carry": annual / 365.0,
    }


def maintenance_excess_estimated(
    net_equity: float, long_equity_market_value: float
) -> float:
    return net_equity - MAINTENANCE_RATE * long_equity_market_value


def realized_daily_volatility(closes: Sequence[float], window: int = VOL_WINDOW) -> float:
    """Sample standard deviation of the last `window` close-to-close log returns."""
    arr = np.asarray(list(closes), dtype=float)
    if len(arr) < window + 1:
        raise ValueError(f"need at least {window + 1} closes, got {len(arr)}")
    tail = arr[-(window + 1) :]
    log_returns = np.diff(np.log(tail))
    return float(np.std(log_returns, ddof=1))


def wilder_atr(
    high: Sequence[float],
    low: Sequence[float],
    close: Sequence[float],
    period: int = ATR_PERIOD,
) -> float:
    """Wilder ATR. The seed is a simple average of the first `period` true ranges."""
    highs = np.asarray(list(high), dtype=float)
    lows = np.asarray(list(low), dtype=float)
    closes = np.asarray(list(close), dtype=float)
    if not (len(highs) == len(lows) == len(closes)):
        raise ValueError("high, low, and close must be the same length")
    if len(closes) < period:
        raise ValueError(f"need at least {period} bars, got {len(closes)}")
    true_ranges = np.empty(len(closes), dtype=float)
    true_ranges[0] = highs[0] - lows[0]
    for i in range(1, len(closes)):
        true_ranges[i] = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )
    atr = float(np.mean(true_ranges[:period]))
    for tr in true_ranges[period:]:
        atr = (atr * (period - 1) + float(tr)) / period
    return atr


def stop_limit_trigger(current_price: float, atr: float) -> float:
    """1.5x ATR stop, floored at 70% of price so a wide bar cannot go negative."""
    raw = current_price - ATR_MULTIPLE * atr
    floor = current_price * 0.70
    return max(floor, raw)


def stop_is_vol_capped(current_price: float, atr: float) -> bool:
    """True when 1.5x ATR would cut more than 30% off the price."""
    if current_price <= 0:
        return False
    return ATR_MULTIPLE * atr >= current_price * 0.30


def annotate_position_impact(
    positions: list[dict[str, Any]],
    *,
    net_equity: float,
    margin_used: float,
    last_closes: Mapping[str, float | None] | None = None,
) -> None:
    """Dollar cost, break-even equity, signal, and the 30-day underlying target."""
    closes = last_closes or {}
    for row in positions:
        shares = float(row.get("shares") or 0.0)
        price = float(row.get("current_price") or 0.0)
        avg_cost = row.get("avg_cost")
        market_value = float(row.get("market_value") or 0.0)
        cost = None if avg_cost is None else float(avg_cost) * shares
        if cost is None:
            gain = None
        elif price >= float(avg_cost):
            gain = 0.0
        else:
            gain = max(cost - market_value, 0.0)
        row["cost_basis"] = cost
        row["breakeven_gain_usd"] = gain
        row["equity_if_breakeven"] = None if gain is None else float(net_equity) + gain
        row["clears_margin"] = cost is not None and cost > float(margin_used)
        atr = row.get("atr_14")
        if atr is not None and price > 0:
            row["stop_limit_trigger"] = stop_limit_trigger(price, float(atr))
            row["vol_capped"] = stop_is_vol_capped(price, float(atr))
        else:
            row["vol_capped"] = False
        symbol = row.get("underlying_symbol")
        spot = closes.get(str(symbol)) if symbol and str(symbol) in closes else row.get("underlying_price")
        row["underlying_price"] = None if spot is None else float(spot)
        rally = row.get("breakeven_underlying_30d")
        if row["underlying_price"] is None or rally is None:
            row["underlying_target_30d"] = None
        else:
            row["underlying_target_30d"] = float(row["underlying_price"]) * (1.0 + float(rally))
    levered = [row for row in positions if float(row.get("leverage") or 1.0) > 1.0]
    core = max(levered, key=lambda row: float(row.get("market_value") or 0.0))["ticker"] if levered else None
    for row in positions:
        row["signal"] = _position_signal(row, core)


def _position_signal(row: Mapping[str, Any], core_ticker: str | None) -> str:
    if float(row.get("leverage") or 1.0) <= 1.0:
        return "1X HOLD"
    if core_ticker is not None and row.get("ticker") == core_ticker:
        return "CORE DRIVER"
    cost = row.get("cost_basis")
    gain = row.get("breakeven_gain_usd")
    if cost not in (None, 0) and gain is not None and float(gain) / float(cost) < 0.15:
        return "NEAR BE"
    return "HIGH DECAY"


def underlying_candidates(ticker: str, meta: Mapping[str, Any]) -> list[str]:
    """Vol underlyings. Benchmark ETF first, then its US fallback, else the news ticker."""
    if meta.get("benchmark_etf"):
        ordered = [str(meta["benchmark_etf"])]
        for symbol in meta.get("news_tickers") or []:
            text = str(symbol)
            if "." in text or text in ordered:
                continue
            ordered.append(text)
            break
        return ordered
    news = [str(symbol) for symbol in (meta.get("news_tickers") or [ticker])]
    return news[:1] or [ticker]


def weight_key_matches(key: str, ticker: str) -> bool:
    if key == ticker:
        return True
    return key.rsplit("_", 1)[-1] == ticker


def news_ticker_weight(meta: Mapping[str, Any], news_ticker: str) -> float:
    """Share of this holding's look-through that the news ticker represents."""
    weights = dict(meta.get("top_weights") or {})
    for key, weight in weights.items():
        if weight_key_matches(str(key), news_ticker):
            return float(weight)
    news = [str(symbol) for symbol in (meta.get("news_tickers") or [])]
    holding = str(meta.get("ticker") or "")
    if not weights:
        if news_ticker == holding or (len(news) == 1 and news_ticker in news):
            return 1.0
        if news_ticker in news and news:
            return 1.0 / len(news)
        return 0.0
    covered: set[str] = set()
    for key in weights:
        covered.add(str(key))
        covered.add(str(key).rsplit("_", 1)[-1])
    uncovered = [symbol for symbol in news if symbol not in covered]
    if news_ticker in uncovered and uncovered:
        residual = max(0.0, 1.0 - sum(float(value) for value in weights.values()))
        return residual / len(uncovered)
    if news_ticker == holding:
        return 1.0
    return 0.0


def korea_gap(market_value: float, leverage: float, top_weights: Mapping[str, Any]) -> dict[str, float]:
    notional = look_through(market_value, leverage)
    samsung = float(top_weights.get(KOREA_SAMSUNG_KEY, 0.0))
    hynix = float(top_weights.get(KOREA_HYNIX_KEY, 0.0))
    return {
        "samsung_usd": notional * samsung,
        "sk_hynix_usd": notional * hynix,
        "combined_usd": notional * (samsung + hynix),
        "samsung_weight": samsung,
        "sk_hynix_weight": hynix,
    }


def account_summaries(book: Mapping[str, Any]) -> list[dict[str, Any]]:
    summaries = []
    for account in book.get("accounts") or []:
        summaries.append(
            {
                "label": account.get("label"),
                "account_mask": account.get("account_mask"),
                "account_type": account.get("account_type"),
                "nickname": account.get("nickname"),
                "is_default": bool(account.get("is_default")),
                "is_agentic": bool(account.get("is_agentic")),
                "cash": account.get("cash"),
                "buying_power": account.get("buying_power"),
                "total_value": account.get("total_value"),
            }
        )
    return summaries


def snapshot_rows(
    book: Mapping[str, Any], as_of: datetime | None = None
) -> list[SnapshotRow]:
    """One row per open position. Margin and net equity repeat on every row."""
    moment = as_of or parse_as_of(book)
    rows: list[SnapshotRow] = []
    for account in book.get("accounts") or []:
        carry = gold_carry(float(account.get("cash") or 0.0))
        net_equity = float(account.get("total_value") or 0.0)
        for position in account.get("positions") or []:
            rows.append(
                SnapshotRow(
                    snapshot_ts=moment,
                    ticker=str(position["ticker"]),
                    shares=float(position.get("shares") or 0.0),
                    avg_cost=_optional_float(position.get("avg_cost")),
                    current_price=float(position.get("current_price") or 0.0),
                    market_value=float(position.get("market_value") or 0.0),
                    margin_used=carry["margin_used"],
                    net_equity=net_equity,
                )
            )
    return rows


def build_metrics(
    book: Mapping[str, Any],
    portfolio_map: Mapping[str, Any],
    *,
    sigmas: Mapping[str, float | None],
    atrs: Mapping[str, float | None],
    last_closes: Mapping[str, float | None] | None = None,
) -> dict[str, Any]:
    """Quant block of the audit. Prices and vols are supplied by the caller."""
    as_of = parse_as_of(book)
    primary = select_primary_account(book)
    cash = float(primary.get("cash") or 0.0)
    net_equity = float(primary.get("total_value") or 0.0)
    carry = gold_carry(cash)

    positions: list[dict[str, Any]] = []
    dust: list[dict[str, Any]] = []
    options: list[dict[str, Any]] = []
    equity_market_value = 0.0
    cluster_market_value = 0.0
    cluster_look_through = 0.0
    korea_total = {
        "samsung_usd": 0.0,
        "sk_hynix_usd": 0.0,
        "combined_usd": 0.0,
    }
    korea_sources: list[str] = []

    for raw in primary.get("positions") or []:
        asset_class = str(raw.get("asset_class") or "equity")
        market_value = float(raw.get("market_value") or 0.0)
        if asset_class == "option":
            options.append(_passthrough(raw))
            continue
        if asset_class != "equity":
            if market_value < ACTIVE_MIN_MARKET_VALUE:
                dust.append(_passthrough(raw))
            continue
        if not is_active_position(raw):
            if market_value > 0:
                dust.append(_passthrough(raw))
            continue

        ticker = str(raw["ticker"])
        meta = dict(portfolio_map.get(ticker) or {})
        meta["ticker"] = ticker
        leverage = float(meta.get("leverage") or 1.0)
        equity_market_value += market_value
        notion = look_through(market_value, leverage)
        cluster = meta.get("sector_cluster")
        if cluster == AI_CLUSTER:
            cluster_market_value += market_value
            cluster_look_through += notion

        gap = None
        weights = meta.get("top_weights") or {}
        if KOREA_SAMSUNG_KEY in weights or KOREA_HYNIX_KEY in weights:
            gap = korea_gap(market_value, leverage, weights)
            korea_total["samsung_usd"] += gap["samsung_usd"]
            korea_total["sk_hynix_usd"] += gap["sk_hynix_usd"]
            korea_total["combined_usd"] += gap["combined_usd"]
            korea_sources.append(ticker)

        candidates = underlying_candidates(ticker, meta) if meta else [ticker]
        sigma, sigma_symbol, sigma_note = _resolve_sigma(candidates, sigmas)
        drag = None if sigma is None else daily_variance_drag(leverage, sigma)
        atr = atrs.get(ticker)
        price = float(raw.get("current_price") or 0.0)
        avg_cost = _optional_float(raw.get("avg_cost"))
        rallies: dict[str, float | None] = {}
        for horizon in BREAKEVEN_HORIZONS:
            key = f"breakeven_underlying_{horizon}d"
            if avg_cost is None or sigma is None or price <= 0 or drag is None:
                rallies[key] = None
            else:
                rallies[key] = required_underlying_rally(
                    avg_cost, price, leverage, drag, horizon
                )
        catalyst = meta.get("next_major_catalyst")
        days_to = None
        if isinstance(catalyst, dict) and catalyst.get("date"):
            event_day = datetime.fromisoformat(str(catalyst["date"])).date()
            days_to = (event_day - as_of.date()).days
        unrealized = None
        if avg_cost is not None:
            unrealized = (price - avg_cost) * float(raw.get("shares") or 0.0)

        positions.append(
            {
                "ticker": ticker,
                "name": meta.get("name"),
                "asset_class": asset_class,
                "shares": float(raw.get("shares") or 0.0),
                "avg_cost": avg_cost,
                "current_price": price,
                "market_value": market_value,
                "unrealized_pnl": unrealized,
                "leverage": leverage,
                "look_through_usd": notion,
                "sector_cluster": cluster,
                "news_tickers": list(meta.get("news_tickers") or []),
                "top_weights": dict(weights),
                "underlying_symbol": sigma_symbol,
                "sigma_daily": sigma,
                "sigma_note": sigma_note,
                "daily_variance_drag": drag,
                **rallies,
                "breakeven_note": BREAKEVEN_NOTE,
                "atr_14": None if atr is None else float(atr),
                "stop_limit_trigger": (
                    None if atr is None else stop_limit_trigger(price, float(atr))
                ),
                "next_major_catalyst": catalyst,
                "days_to_catalyst": days_to,
                "within_14_days": days_to is not None and 0 <= days_to <= 14,
                "korea_overnight_gap": gap,
                "mapped": ticker in portfolio_map,
            }
        )

    weight = (
        cluster_market_value / equity_market_value if equity_market_value else 0.0
    )
    estimated_excess = maintenance_excess_estimated(net_equity, equity_market_value)
    return _finish_metrics({
        "as_of": as_of.isoformat(),
        "primary_account_mask": primary.get("account_mask"),
        "accounts": account_summaries(book),
        "margin": {
            "cash": cash,
            "pending_deposits": float(primary.get("pending_deposits") or 0.0),
            "buying_power": primary.get("buying_power"),
            "unleveraged_buying_power": primary.get("unleveraged_buying_power"),
            "crypto_buying_power": primary.get("crypto_buying_power"),
            "net_equity": net_equity,
            "long_equity_market_value": equity_market_value,
            **carry,
            "maintenance_excess": None,
            "maintenance_excess_estimated": estimated_excess,
            "maintenance_excess_note": MAINTENANCE_NOTE,
        },
        "cluster": {
            "name": AI_CLUSTER,
            "market_value": cluster_market_value,
            "weight": weight,
            "look_through_usd": cluster_look_through,
        },
        "korea_overnight_gap": {
            "source_tickers": korea_sources,
            **korea_total,
            "weights": {
                KOREA_SAMSUNG_KEY: float(
                    (portfolio_map.get(korea_sources[0], {}) if korea_sources else {}).get(
                        "top_weights", {}
                    ).get(KOREA_SAMSUNG_KEY, 0.0)
                ),
                KOREA_HYNIX_KEY: float(
                    (portfolio_map.get(korea_sources[0], {}) if korea_sources else {}).get(
                        "top_weights", {}
                    ).get(KOREA_HYNIX_KEY, 0.0)
                ),
            },
        },
        "positions": positions,
        "dust_positions": dust,
        "options": options,
    }, last_closes)


def _finish_metrics(payload: dict[str, Any], last_closes: Mapping[str, float | None] | None) -> dict[str, Any]:
    margin = payload["margin"]
    annotate_position_impact(
        payload["positions"],
        net_equity=float(margin["net_equity"]),
        margin_used=float(margin["margin_used"]),
        last_closes=last_closes,
    )
    return payload


def _resolve_sigma(
    candidates: list[str], sigmas: Mapping[str, float | None]
) -> tuple[float | None, str | None, str | None]:
    notes: list[str] = []
    for symbol in candidates:
        if symbol not in sigmas:
            continue
        value = sigmas.get(symbol)
        if value is None:
            notes.append(f"{symbol} unavailable")
            continue
        note = None if symbol == candidates[0] else f"fallback from {candidates[0]}"
        return float(value), symbol, note
    if notes:
        return None, candidates[0] if candidates else None, "; ".join(notes)
    return None, candidates[0] if candidates else None, "no volatility supplied"


def _optional_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    return float(value)


def _passthrough(raw: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "ticker": raw.get("ticker"),
        "asset_class": raw.get("asset_class"),
        "shares": raw.get("shares"),
        "avg_cost": raw.get("avg_cost"),
        "current_price": raw.get("current_price"),
        "market_value": raw.get("market_value"),
    }
