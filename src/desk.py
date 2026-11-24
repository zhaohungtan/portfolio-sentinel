"""Local desk payload. Nothing here talks to Robinhood."""

from __future__ import annotations

import json
import math
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from pathlib import Path
from typing import Any, Callable, Mapping

from src.broker_sync import sync_broker_book, write_json_atomic
from src.catalysts import build_calendar
from src.fear_greed import load_fear_greed
from src.margin_prob import simulate_margin, static_maintenance_buffer
from src.news_sentiment import (
    MACRO_PROXIES,
    curate_tape,
    persist_scores,
    score_items,
    sentiment_gauges,
)
from src.performance import (
    RECONSTRUCTED_LABEL,
    download_closes,
    load_trade_journal,
    read_performance,
    reconstruct_equity,
    summarize_performance,
)
from src.quant_engine import (
    annotate_position_impact,
    build_metrics,
    gold_carry,
    is_active_position,
    parse_as_of,
    select_primary_account,
    underlying_candidates,
)

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SIGMA = 0.02


def compose_dashboard(
    root: Path | None = None, *, refresh_quotes: bool = False
) -> dict[str, Any]:
    repo = root or ROOT
    book, source = _load_book(repo)
    primary = select_primary_account(book)
    broker_value = primary.get("total_value") if source == "live" else None
    broker_unrealized = sum(
        float(row["shares"]) * (float(row["current_price"]) - float(row["avg_cost"]))
        for row in primary.get("positions") or []
        if all(row.get(key) is not None for key in ("shares", "current_price", "avg_cost"))
        and row.get("asset_class", "equity") == "equity"
    )
    quotes = None
    if refresh_quotes and source == "live":
        quotes = _mark_book_market_quotes(book)
    portfolio_map = _read_json(repo / "portfolio_map.json")
    audit, sigma_source = _metrics(repo, book, portfolio_map)
    positions = list(audit.get("positions") or [])
    sim_rows = [
        {
            "ticker": row.get("ticker"),
            "market_value": row.get("market_value"),
            "leverage": row.get("leverage") or 1.0,
            "sector_cluster": row.get("sector_cluster"),
            "sigma": row.get("sigma_daily") or 0.0,
        }
        for row in positions
    ]
    margin_used = float((audit.get("margin") or {}).get("margin_used") or 0.0)
    margin = simulate_margin(sim_rows, margin_used)
    as_of = parse_as_of(book)
    as_of_day = as_of.astimezone(ZoneInfo("America/New_York")).date().isoformat()
    calendar = build_calendar(
        portfolio_map,
        positions,
        datetime.now(ZoneInfo("America/Los_Angeles")),
        _sigma_map(positions),
    )
    unrealized = _sum(row.get("unrealized_pnl") for row in positions)
    decay = _sum(
        float(row.get("market_value") or 0.0) * float(row.get("daily_variance_drag") or 0.0)
        for row in positions
    )
    primary = select_primary_account(book)
    capital = _capital(primary, positions, audit)
    annotate_position_impact(
        positions,
        net_equity=capital["net_equity"],
        margin_used=margin_used,
    )
    buffer = static_maintenance_buffer(capital["net_equity"], capital["gross_holdings"])
    scenarios = margin_scenarios(
        positions,
        net_equity=capital["net_equity"],
        gross=capital["gross_holdings"],
        margin_used=margin_used,
        current=margin,
    )
    performance = read_performance(
        repo / "data" / "sentinel.duckdb",
        benchmarks=_benchmark_points(repo),
        unrealized_pnl=unrealized,
        daily_decay_drag=decay,
        margin_used=margin_used,
    )
    if source == "live":
        performance = _with_reconstruction(
            repo,
            positions,
            float(primary.get("cash") or 0.0),
            performance,
            margin_used=margin_used,
            unrealized_pnl=unrealized,
            daily_decay_drag=decay,
            book_as_of=as_of.isoformat(),
        )
    performance["benchmark_curves"] = _rebased_benchmarks(
        performance.get("equity_curve") or [],
        _benchmark_levels(repo, performance),
    )
    performance["same_cash"] = same_cash_comparison(
        net_equity=float(broker_value if broker_value is not None else capital["net_equity"]),
        realized=primary.get("realized_pnl_all"),
        unrealized=broker_unrealized,
        first_activity_date=primary.get("first_activity_date"),
        as_of_date=as_of_day,
        levels=_read_json(repo / "data" / "fixtures" / "sample_benchmarks.json") if source == "fixture" else _read_benchmarks(repo),
    )
    tape = _visible_tape(_read_tape(repo), positions)
    fear_greed = load_fear_greed(repo, start_date=str(primary.get("first_activity_date") or "") or None) if source == "live" else None
    drops = dict(margin["drops"])
    drops["stressed_static_buffer_usd"] = buffer["usd"]
    drops["stressed_static_buffer_pct"] = buffer["pct"]
    korea = audit.get("korea_overnight_gap") or {}
    return {
        "source": source,
        "as_of": as_of.isoformat(),
        "sigma_source": sigma_source,
        "broker_source": book.get("source"),
        "unsupported_positions": primary.get("unsupported_positions", 0),
        "broker_net_equity": broker_value,
        "market_quotes": quotes,
        "accounts": [
            {key: value for key, value in account.items() if key not in {"account_mask", "nickname"}}
            for account in audit.get("accounts") or []
        ],
        "capital": capital,
        "korea": {
            "combined_usd": float(korea.get("combined_usd") or 0.0),
            "samsung_usd": float(korea.get("samsung_usd") or 0.0),
            "sk_hynix_usd": float(korea.get("sk_hynix_usd") or 0.0),
        },
        "margin": {
            "probabilities": margin["probabilities"],
            "drops": drops,
            "pnl_percentiles_21d": margin["pnl_percentiles_21d"],
            "margin_used": margin["margin_used"],
            "equity_value": margin["equity_value"],
            "paths": margin["paths"],
            "degrees_of_freedom": margin["degrees_of_freedom"],
            "stressed_static_buffer_usd": buffer["usd"],
            "stressed_static_buffer_pct": buffer["pct"],
            "daily_gold": gold_carry(-margin_used)["daily_interest_carry"],
            "scenarios": scenarios,
        },
        "performance": performance,
        "fear_greed": fear_greed,
        "next_catalyst": calendar["next"],
        "radar": calendar["radar"],
        "sentiment": sentiment_gauges(tape),
        "heatmap": [
            {
                "ticker": row.get("ticker"),
                "market_value": row.get("market_value"),
                "unrealized_pnl": row.get("unrealized_pnl"),
                "unrealized_pct": _pnl_pct(row),
            }
            for row in positions
        ],
        "positions": positions,
        "news": tape,
    }


def filter_news(
    tape: list[Mapping[str, Any]],
    *,
    window: str = "7d",
    scope: str = "all",
    polarity: str = "all",
) -> list[dict[str, Any]]:
    label = {"24h": "24H", "72h": "72H", "7d": "7D"}.get(window.lower(), "7D")
    scope_name = scope.lower()
    polarity_name = polarity.lower()
    kept: list[dict[str, Any]] = []
    for row in tape:
        if label not in (row.get("windows") or []):
            continue
        if scope_name == "macro" and row.get("scope") != "MACRO":
            continue
        if scope_name == "company" and row.get("scope") != "COMPANY":
            continue
        if polarity_name in {"positive", "negative"} and str(row.get("polarity", "")).lower() != polarity_name:
            continue
        kept.append(dict(row))
    return kept


def sync_news(root: Path | None = None) -> dict[str, Any]:
    """Fetch yfinance headlines for held underlyings and the macro proxies."""
    repo = root or ROOT
    book, _source = _load_book(repo)
    warnings: list[str] = []
    try:
        _refresh_news(repo, book)
    except Exception as exc:
        warnings.append(f"news: {exc}")
    payload = compose_dashboard(repo)
    payload["warnings"] = warnings
    return payload


Quote = tuple[float, datetime]


def _fetch_market_quotes(symbols: list[str]) -> dict[str, Quote]:
    import yfinance as yf

    frame = yf.download(
        symbols, period="5d", interval="1m", prepost=True, auto_adjust=False,
        group_by="ticker", multi_level_index=True, progress=False, timeout=5,
    )
    quotes = {}
    for symbol in symbols:
        key = (symbol, "Close")
        if key in frame:
            closes = frame[key].dropna()
            if not closes.empty:
                quotes[symbol] = (float(closes.iloc[-1]), closes.index[-1].to_pydatetime())
    return quotes


def _mark_book_market_quotes(
    book: dict[str, Any],
    fetcher: Callable[[list[str]], dict[str, Quote]] = _fetch_market_quotes,
) -> dict[str, Any]:
    """Overlay market marks on an in-memory broker snapshot."""
    primary = select_primary_account(book)
    positions = [
        row for row in primary.get("positions") or []
        if row.get("asset_class", "equity") == "equity"
        and row.get("ticker") and float(row.get("shares") or 0) != 0
    ]
    symbols = sorted({str(row["ticker"]) for row in positions})
    status: dict[str, Any] = {
        "source": "Yahoo Finance",
        "oldest_as_of": None,
        "latest_as_of": None,
        "updated": [],
        "unchanged": symbols,
    }
    if not symbols:
        return status
    try:
        quotes = fetcher(symbols)
    except Exception:
        return status
    snapshot_time = parse_as_of(book)
    if snapshot_time.tzinfo is None:
        snapshot_time = snapshot_time.replace(tzinfo=ZoneInfo("America/Los_Angeles"))
    now = datetime.now(timezone.utc)
    times: dict[str, datetime] = {}
    difference = 0.0
    for row in positions:
        symbol = str(row["ticker"])
        if symbol not in quotes:
            continue
        price, quote_at = quotes[symbol]
        if (
            not math.isfinite(price) or price <= 0 or quote_at.tzinfo is None
            or not snapshot_time < quote_at <= now
            or row.get("market_value") is None
        ):
            continue
        value = float(row["shares"]) * price
        difference += value - float(row["market_value"])
        row.update(current_price=price, market_value=value)
        times[symbol] = quote_at
    if times and primary.get("total_value") is not None:
        primary["total_value"] = round(float(primary["total_value"]) + difference, 2)
    if times:
        status.update(
            oldest_as_of=min(times.values()).isoformat(),
            latest_as_of=max(times.values()).isoformat(),
            updated=sorted(times),
            unchanged=sorted(set(symbols) - times.keys()),
        )
    return status


def refresh_offline(root: Path | None = None) -> dict[str, Any]:
    """Recompute and persist analytics from the saved broker snapshot."""
    repo = root or ROOT
    warnings: list[str] = []
    book, _source = _load_book(repo)
    book_path = _book_path(repo)
    try:
        from src.cli import run_audit

        run_audit(
            book_path,
            repo / "portfolio_map.json",
            repo / "data" / "sentinel.duckdb",
            repo / "data" / "latest_audit.json",
        )
    except Exception as exc:
        warnings.append(f"audit: {exc}")
    try:
        _refresh_news(repo, book)
    except Exception as exc:
        warnings.append(f"news: {exc}")
    try:
        _write_reconstruction(repo, book)
    except Exception as exc:
        warnings.append(f"reconstruction: {exc}")
    try:
        _refresh_benchmarks(repo)
    except Exception as exc:
        warnings.append(f"benchmarks: {exc}")
    journal = repo / "data" / "trade_journal.json"
    if journal.exists():
        load_trade_journal(repo / "data" / "sentinel.duckdb", journal)
    payload = compose_dashboard(repo)
    payload["warnings"] = warnings
    return payload


def _refresh_news(repo: Path, book: Mapping[str, Any]) -> None:
    from src.db import SentinelDB
    from src.news_sentinel import expanded_news_tickers, fetch_news
    portfolio_map = _read_json(repo / "portfolio_map.json")
    held = [
        str(row["ticker"])
        for row in (select_primary_account(book).get("positions") or [])
        if str(row.get("asset_class") or "equity") == "equity" and is_active_position(row)
    ]
    symbols = list(MACRO_PROXIES)
    for symbol in expanded_news_tickers(portfolio_map, held):
        if symbol not in symbols:
            symbols.append(symbol)
    items: list[dict[str, Any]] = []
    for symbol in symbols:
        try:
            batch = fetch_news(symbol)
        except Exception:
            continue
        for raw in batch:
            row = dict(raw)
            row["ticker"] = symbol
            if symbol in MACRO_PROXIES:
                row["scope"] = "MACRO"
            items.append(row)
    now = parse_as_of(book)
    positions = _metrics(repo, book, portfolio_map)[0].get("positions") or []
    scored = score_items(items, positions, now=now)
    tape_path = repo / "data" / "news_tape.json"
    tape_path.parent.mkdir(parents=True, exist_ok=True)
    tape_path.write_text(json.dumps(scored, indent=2) + "\n", encoding="utf-8")
    db_path = repo / "data" / "sentinel.duckdb"
    if db_path.exists() and scored:
        with SentinelDB(db_path) as db:
            persist_scores(db, scored, now)


def refresh_broker_dashboard(root: Path | None = None) -> dict[str, Any]:
    repo = root or ROOT
    book = sync_broker_book(repo)
    primary = select_primary_account(book)
    warnings: list[str] = []
    try:
        _refresh_benchmarks(repo, primary.get("first_activity_date"))
    except Exception:
        warnings.append("Benchmark refresh failed. Showing the last available benchmark prices.")
    if primary.get("unsupported_positions"):
        warnings.append("Robinhood net equity includes options. Position-level charts currently cover stocks and supported crypto marks.")
    dashboard = compose_dashboard(repo)
    dashboard["warnings"] = warnings
    return dashboard


def _refresh_benchmarks(repo: Path, first_activity_date: str | None = None) -> None:
    from src.performance import fetch_benchmark_levels

    today = datetime.now(ZoneInfo("America/New_York")).date()
    start = date.fromisoformat(first_activity_date) - timedelta(days=7) if first_activity_date else date(today.year, 1, 1)
    levels = fetch_benchmark_levels(start.isoformat(), (today + timedelta(days=1)).isoformat())
    saved = _read_benchmarks(repo)
    for symbol, rows in levels.items():
        if rows:
            saved[symbol] = rows
    if not all(levels.get(symbol) for symbol in ("QQQ", "SPY")):
        write_json_atomic(repo / "data" / "benchmarks.json", saved)
        raise RuntimeError("Incomplete benchmark prices")
    write_json_atomic(repo / "data" / "benchmarks.json", saved)


def _metrics(
    repo: Path, book: Mapping[str, Any], portfolio_map: Mapping[str, Any]
) -> tuple[dict[str, Any], str]:
    audit_path = repo / "data" / "latest_audit.json"
    cached = _read_json(audit_path) if audit_path.exists() else {}
    cached_rows = cached.get("positions") or []
    if cached_rows:
        return build_metrics(
            book,
            portfolio_map,
            sigmas=_sigma_map(cached_rows),
            atrs={row["ticker"]: row.get("atr_14") for row in cached_rows},
            last_closes={
                row["underlying_symbol"]: row["underlying_price"]
                for row in cached_rows if row.get("underlying_symbol") and row.get("underlying_price")
            },
        ), "audit indicators"
    sigmas: dict[str, float] = {}
    atrs: dict[str, None] = {}
    for ticker, meta in portfolio_map.items():
        atrs[str(ticker)] = None
        for symbol in underlying_candidates(str(ticker), meta):
            sigmas[symbol] = DEFAULT_SIGMA
    return build_metrics(book, portfolio_map, sigmas=sigmas, atrs=atrs), "default-2pct"


def _sigma_map(positions: list[Mapping[str, Any]]) -> dict[str, float]:
    found: dict[str, float] = {}
    for row in positions:
        sigma = row.get("sigma_daily")
        symbol = row.get("underlying_symbol") or row.get("ticker")
        if sigma is not None and symbol:
            found[str(symbol)] = float(sigma)
    return found


def _load_book(repo: Path) -> tuple[dict[str, Any], str]:
    path = _book_path(repo)
    source = "live" if path.name == "live_book.json" else "fixture"
    return _read_json(path), source


def _book_path(repo: Path) -> Path:
    live = repo / "data" / "live_book.json"
    if live.exists():
        return live
    return repo / "data" / "fixtures" / "sample_book.json"


def _read_tape(repo: Path) -> list[dict[str, Any]]:
    path = repo / "data" / "news_tape.json"
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    return list(payload if isinstance(payload, list) else [])


def _read_benchmarks(repo: Path) -> dict[str, list[dict[str, Any]]]:
    path = repo / "data" / "benchmarks.json"
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return dict(payload)


def _benchmark_points(repo: Path) -> dict[str, list[tuple[datetime, float]]]:
    points: dict[str, list[tuple[datetime, float]]] = {}
    for symbol, rows in _read_benchmarks(repo).items():
        series = []
        for row in rows:
            series.append((datetime.fromisoformat(str(row["date"]) + "T00:00:00"), float(row["close"])))
        points[symbol] = series
    return points


def _rebased_benchmarks(
    curve: list[Mapping[str, Any]],
    levels: Mapping[str, list[Mapping[str, Any]]],
) -> dict[str, list[dict[str, Any]]]:
    if not curve:
        return {}
    start_equity = float(curve[0]["net_equity"])
    start_day = str(curve[0]["date"])
    rebased: dict[str, list[dict[str, Any]]] = {}
    for symbol, rows in levels.items():
        ordered = sorted(rows, key=lambda row: str(row["date"]))
        base = None
        for row in ordered:
            if str(row["date"]) <= start_day:
                base = float(row["close"])
        if not base:
            continue
        rebased[symbol] = [
            {
                "date": str(row["date"]),
                "value": start_equity * float(row["close"]) / base,
            }
            for row in ordered
            if str(row["date"]) >= start_day and float(row["close"]) > 0
        ]
    return rebased


def same_cash_comparison(
    *,
    net_equity: float,
    realized: Any,
    unrealized: float,
    first_activity_date: Any,
    as_of_date: str,
    levels: Mapping[str, list[Mapping[str, Any]]],
) -> dict[str, Any] | None:
    """Cash put in, then that same cash in QQQ and the S&P 500.

    Money in is net equity minus all-time realized profit minus open unrealized
    profit. The portfolio line has those two known values. The index lines are
    that cash invested on the first activity date.
    """
    if realized is None or not first_activity_date:
        return None
    start = str(first_activity_date)[:10]
    contributed = float(net_equity) - float(realized) - float(unrealized)
    if contributed <= 0:
        return None
    portfolio = [{"date": start, "value": contributed}]
    if as_of_date != start:
        portfolio.append({"date": as_of_date, "value": float(net_equity)})
    benchmarks = {
        symbol: _invested_path(contributed, start, [
            row for row in levels.get(symbol, []) if str(row["date"]) <= as_of_date
        ])
        for symbol in ("QQQ", "SPY")
    }
    qqq, spy = benchmarks["QQQ"], benchmarks["SPY"]
    qqq_now = qqq[-1]["value"] if qqq else None
    spy_now = spy[-1]["value"] if spy else None
    return {
        "money_in": contributed,
        "net_equity": float(net_equity),
        "change_usd": float(net_equity) - contributed,
        "change_pct": float(net_equity) / contributed - 1.0,
        "first_activity_date": start,
        "portfolio": portfolio,
        "benchmarks": benchmarks,
        "qqq_now": qqq_now,
        "spy_now": spy_now,
        "alpha_qqq": _ending_gap(float(net_equity), qqq_now, contributed),
        "alpha_spy": _ending_gap(float(net_equity), spy_now, contributed),
    }


def _ending_gap(net_equity: float, ending: float | None, money_in: float) -> float | None:
    if ending is None or money_in == 0:
        return None
    return (net_equity - ending) / money_in


def _invested_path(
    money_in: float,
    start: str,
    rows: list[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    ordered = sorted(rows, key=lambda row: str(row["date"]))
    base_row = None
    for row in ordered:
        close = float(row.get("close") or 0.0)
        if str(row["date"]) <= start and close > 0:
            base_row = row
    if base_row is None:
        return []
    base = float(base_row["close"])
    path = [{"date": str(base_row["date"]), "value": money_in}]
    for row in ordered:
        if str(row["date"]) <= str(base_row["date"]):
            continue
        close = float(row.get("close") or 0.0)
        if close <= 0:
            continue
        path.append({"date": str(row["date"]), "value": money_in * close / base})
    return path


def _capital(
    primary: Mapping[str, Any],
    positions: list[Mapping[str, Any]],
    audit: Mapping[str, Any],
) -> dict[str, float]:
    cash = float(primary.get("cash") or 0.0)
    gross = 0.0
    for row in primary.get("positions") or []:
        if str(row.get("asset_class") or "equity") == "option":
            continue
        gross += float(row.get("market_value") or 0.0)
    look = sum(float(row.get("look_through_usd") or 0.0) for row in positions)
    korea = float((audit.get("korea_overnight_gap") or {}).get("combined_usd") or 0.0)
    return {
        "net_equity": float(primary.get("total_value") or 0.0),
        "gross_holdings": gross,
        "margin_debt": cash if cash < 0 else 0.0,
        "look_through_usd": look,
        "korea_overnight_usd": korea,
    }


def margin_scenarios(
    positions: list[Mapping[str, Any]],
    *,
    net_equity: float,
    gross: float,
    margin_used: float,
    current: Mapping[str, Any] | None = None,
    n_paths: int = 10_000,
) -> list[dict[str, Any]]:
    """Four books. A sale keeps net equity and pays down the debit."""
    specs: list[tuple[str, str, dict[str, float] | None]] = [
        ("current", "Current", {}),
        ("trim_ram", "Trim 50% RAM", {"RAM": 0.5}),
        ("close_nebx_smcx", "Close NEBX+SMCX", {"NEBX": 1.0, "SMCX": 1.0}),
        ("zero_margin", "Zero Margin", None),
    ]
    scenarios: list[dict[str, Any]] = []
    for key, label, cuts in specs:
        if cuts is None:
            scenario_net = float(net_equity) + float(margin_used)
            scenario_gross = float(gross)
            scenario_margin = 0.0
            rows = [_sim_row(row, float(row.get("market_value") or 0.0)) for row in positions]
            simulation = None
        else:
            rows = []
            sold = 0.0
            for row in positions:
                value = float(row.get("market_value") or 0.0)
                fraction = float(cuts.get(str(row.get("ticker")), 0.0))
                sold += value * fraction
                kept = value * (1.0 - fraction)
                if kept <= 0:
                    continue
                rows.append(_sim_row(row, kept))
            scenario_net = float(net_equity)
            scenario_gross = max(float(gross) - sold, 0.0)
            scenario_margin = max(float(margin_used) - sold, 0.0)
            simulation = current if key == "current" and current is not None else None
        if simulation is None:
            simulation = simulate_margin(rows, scenario_margin, n_paths=n_paths)
        buffer = static_maintenance_buffer(scenario_net, scenario_gross)
        probabilities = simulation.get("probabilities") or {}
        scenarios.append(
            {
                "id": key,
                "label": label,
                "buffer_usd": buffer["usd"],
                "buffer_pct": buffer["pct"],
                "daily_gold": gold_carry(-scenario_margin)["daily_interest_carry"],
                "stressed_5d": float((probabilities.get("5") or {}).get("stressed") or 0.0),
                "stressed_21d": float((probabilities.get("21") or {}).get("stressed") or 0.0),
                "margin_used": scenario_margin,
                "net_equity": scenario_net,
                "gross_holdings": scenario_gross,
            }
        )
    return scenarios


def _sim_row(row: Mapping[str, Any], market_value: float) -> dict[str, Any]:
    return {
        "ticker": row.get("ticker"),
        "market_value": market_value,
        "leverage": row.get("leverage") or 1.0,
        "sector_cluster": row.get("sector_cluster"),
        "sigma": row.get("sigma_daily") if row.get("sigma_daily") is not None else row.get("sigma") or 0.0,
    }


def _with_reconstruction(
    repo: Path,
    positions: list[Mapping[str, Any]],
    cash: float,
    performance: dict[str, Any],
    *,
    margin_used: float,
    unrealized_pnl: float,
    daily_decay_drag: float,
    book_as_of: str = "",
) -> dict[str, Any]:
    curve = list(performance.get("equity_curve") or [])
    if len({str(point.get("date")) for point in curve}) >= 5:
        return performance
    payload = _read_reconstruction(repo)
    cached_as_of = str((payload or {}).get("as_of") or "")
    if payload is None or (book_as_of and cached_as_of < book_as_of):
        fresh = _write_reconstruction_from_positions(repo, positions, cash, as_of=book_as_of)
        if fresh is not None:
            payload = fresh
    curve = list((payload or {}).get("equity_curve") or [])
    if len(curve) < 2:
        return performance
    points = [(_stamp(row["date"]), float(row["net_equity"])) for row in curve]
    saved = _benchmark_points(repo)
    benchmarks: dict[str, list[tuple[datetime, float]]] = {}
    for symbol, key in (("SMH", "smh"), ("QQQ", "qqq"), ("SPY", "spy")):
        series = [(_stamp(row["date"]), float(row["close"])) for row in (payload or {}).get(key) or []]
        if len(series) < 2:
            series = list(saved.get(symbol) or [])
        if len(series) >= 2:
            benchmarks[symbol] = series
    rebuilt = summarize_performance(
        points,
        margin_used=margin_used,
        unrealized_pnl=unrealized_pnl,
        daily_decay_drag=daily_decay_drag,
        benchmarks=benchmarks or None,
    )
    rebuilt["track_record"] = RECONSTRUCTED_LABEL
    return rebuilt


def _write_reconstruction(repo: Path, book: Mapping[str, Any]) -> None:
    portfolio_map = _read_json(repo / "portfolio_map.json")
    audit, _source = _metrics(repo, book, portfolio_map)
    positions = [row for row in (audit.get("positions") or []) if is_active_position(row)]
    cash = float(select_primary_account(book).get("cash") or 0.0)
    as_of = str(book.get("as_of") or "")
    _write_reconstruction_from_positions(repo, positions, cash, as_of=as_of)


def _write_reconstruction_from_positions(
    repo: Path,
    positions: list[Mapping[str, Any]],
    cash: float,
    *,
    as_of: str = "",
) -> dict[str, Any] | None:
    symbols = [str(row.get("ticker")) for row in positions if row.get("ticker")]
    closes = download_closes([*symbols, "SMH", "QQQ", "SPY"])
    curve = reconstruct_equity(positions, cash, closes)
    if len(curve) < 2:
        return None
    payload = {
        "label": RECONSTRUCTED_LABEL,
        "as_of": as_of,
        "equity_curve": [
            {"date": day.date().isoformat(), "net_equity": value} for day, value in curve
        ],
        "smh": _close_rows(closes.get("SMH") or []),
        "qqq": _close_rows(closes.get("QQQ") or []),
        "spy": _close_rows(closes.get("SPY") or []),
    }
    path = repo / "data" / "reconstructed_equity.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return payload


def _read_reconstruction(repo: Path) -> dict[str, Any] | None:
    path = repo / "data" / "reconstructed_equity.json"
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else None


def _close_rows(series: list[tuple[datetime, float]]) -> list[dict[str, Any]]:
    return [{"date": day.date().isoformat(), "close": price} for day, price in series]


def _stamp(value: str) -> datetime:
    text = str(value)
    if "T" not in text:
        text += "T00:00:00"
    return datetime.fromisoformat(text)


def _benchmark_levels(
    repo: Path, performance: Mapping[str, Any]
) -> dict[str, list[dict[str, Any]]]:
    levels = dict(_read_benchmarks(repo))
    cached = _read_reconstruction(repo) or {}
    for symbol, key in (("SMH", "smh"), ("QQQ", "qqq"), ("SPY", "spy")):
        if levels.get(symbol):
            continue
        if performance.get("track_record") != RECONSTRUCTED_LABEL and symbol == "SMH":
            continue
        rows = list(cached.get(key) or [])
        if rows:
            levels[symbol] = rows
    return levels


def _visible_tape(
    tape: list[Mapping[str, Any]], positions: list[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    held = {str(row.get("ticker")) for row in positions}
    symbols = set(held)
    for row in positions:
        for ticker in row.get("news_tickers") or []:
            symbols.add(str(ticker))
    visible: list[dict[str, Any]] = []
    for item in tape:
        scope = str(item.get("scope") or "")
        ticker = str(item.get("ticker") or "")
        if scope == "MACRO" or ticker in MACRO_PROXIES:
            visible.append(dict(item))
            continue
        linked = {str(name) for name in (item.get("held_tickers") or [])}
        if ticker in symbols or linked & held:
            visible.append(dict(item))
    return curate_tape(visible)


def _pnl_pct(row: Mapping[str, Any]) -> float | None:
    avg = row.get("avg_cost")
    price = row.get("current_price")
    if avg in (None, 0) or price is None:
        return None
    return float(price) / float(avg) - 1.0


def _sum(values: Any) -> float:
    total = 0.0
    for value in values:
        if value is None:
            continue
        total += float(value)
    return total


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))
