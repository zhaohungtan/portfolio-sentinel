"""Commands: `sentinel smoke` (offline) and `sentinel audit` (live book)."""

from __future__ import annotations

import argparse
import json
import math
import tempfile
from datetime import timedelta
from pathlib import Path
from typing import Any, Callable, Mapping

from src.db import SentinelDB
from src.map_sync import fetch_profile, sync_missing
from src.news_sentinel import collect_news, fetch_news, ingest_headlines
from src.quant_engine import (
    BREAKEVEN_NOTE,
    MAINTENANCE_NOTE,
    build_metrics,
    parse_as_of,
    realized_daily_volatility,
    snapshot_rows,
    underlying_candidates,
    wilder_atr,
)

ROOT = Path(__file__).resolve().parents[1]
HistoryFetcher = Callable[[str], Any]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="sentinel")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("smoke", help="Offline checks against the Nov 22 fixture")
    audit = commands.add_parser("audit", help="Map sync, quant, news, and audit JSON")
    audit.add_argument("--book", type=Path, default=ROOT / "data" / "live_book.json")
    audit.add_argument("--map", type=Path, default=ROOT / "portfolio_map.json")
    audit.add_argument("--db", type=Path, default=ROOT / "data" / "sentinel.duckdb")
    audit.add_argument("--out", type=Path, default=ROOT / "data" / "latest_audit.json")
    args = parser.parse_args(argv)
    if args.command == "smoke":
        summary = run_smoke()
        print("smoke ok")
        print(f"RAM look-through ${summary['ram_look_through']:,.2f}")
        print(f"Korea Samsung ${summary['korea_samsung']:,.2f}")
        print("2x daily drag equals sigma^2")
        print("headline deduped")
        return 0
    report = run_audit(args.book, args.map, args.db, args.out)
    print(args.out)
    print(f"positions {len(report['positions'])}")
    print(f"new catalysts {len(report['new_catalysts'])}")
    print(f"auto-mapped {len(report['new_holdings_auto_mapped'])}")
    return 0


def run_smoke(root: Path | None = None) -> dict[str, float]:
    """Fixture math and headline dedup. No network and no MCP."""
    repo = root or ROOT
    book = _read_json(repo / "data" / "fixtures" / "sample_book.json")
    portfolio_map = _read_json(repo / "portfolio_map.json")
    sigmas: dict[str, float] = {}
    atrs: dict[str, float] = {}
    for ticker, meta in portfolio_map.items():
        atrs[str(ticker)] = 1.0
        for symbol in underlying_candidates(str(ticker), meta):
            sigmas[symbol] = 0.02
    metrics = build_metrics(book, portfolio_map, sigmas=sigmas, atrs=atrs)
    ram = next(row for row in metrics["positions"] if row["ticker"] == "RAM")
    if not math.isclose(ram["look_through_usd"], ram["market_value"] * 2.0):
        raise AssertionError("RAM look-through is not market value times 2")
    expected_samsung = ram["market_value"] * 2.0 * 0.2825
    actual_samsung = metrics["korea_overnight_gap"]["samsung_usd"]
    if not math.isclose(actual_samsung, expected_samsung):
        raise AssertionError("Korea Samsung exposure does not match RAM weights")
    sigma = ram["sigma_daily"]
    if sigma is None or not math.isclose(ram["daily_variance_drag"], sigma**2):
        raise AssertionError("2x daily variance drag is not sigma^2")

    now = parse_as_of(book)
    headline = {
        "ticker": "MU",
        "title": "Micron earnings guidance raised",
        "publisher": "fixture",
        "url": None,
        "published_at": now - timedelta(hours=2),
    }
    with tempfile.TemporaryDirectory() as tmp:
        with SentinelDB(Path(tmp) / "smoke.duckdb") as db:
            first = ingest_headlines(db, [headline], metrics["positions"], now=now)
            second = ingest_headlines(db, [headline], metrics["positions"], now=now)
    if len(first["new_catalysts"]) != 1 or first["new_catalysts"][0]["headline_hash"] == "":
        raise AssertionError("expected one new headline")
    if second["new_catalysts"] or len(second["developing_catalysts"]) != 1:
        raise AssertionError("repeat headline was not deduped")
    return {
        "ram_look_through": float(ram["look_through_usd"]),
        "korea_samsung": float(actual_samsung),
    }


def run_audit(
    book_path: Path,
    map_path: Path,
    db_path: Path,
    out_path: Path,
    *,
    profile_fetcher: Callable[[str], Mapping[str, Any]] | None = None,
    history_fetcher: HistoryFetcher | None = None,
    news_fetcher: Callable[[str], list[Mapping[str, Any]]] | None = None,
) -> dict[str, Any]:
    """Sync the map, persist the book, and write data/latest_audit.json."""
    book = _read_json(book_path)
    sync = sync_missing(
        book,
        map_path,
        profile_fetcher or fetch_profile,
        today=parse_as_of(book).date(),
    )
    portfolio_map = sync["map"]
    held = [
        str(position["ticker"])
        for position in _primary_positions(book)
        if str(position.get("asset_class") or "equity") == "equity"
    ]
    symbols = _market_symbols(held, portfolio_map)
    sigmas, atrs, closes = _load_market(symbols, history_fetcher or fetch_history)
    metrics = build_metrics(
        book, portfolio_map, sigmas=sigmas, atrs=atrs, last_closes=closes
    )
    rows = snapshot_rows(book)
    with SentinelDB(db_path) as db:
        marks = db.record_book(rows)
        news = collect_news(
            portfolio_map,
            metrics["positions"],
            db,
            news_fetcher or fetch_news,
            now=parse_as_of(book),
        )
    for position in metrics["positions"]:
        mark = marks.get(position["ticker"])
        if mark is None:
            continue
        position["peak_price"] = mark.peak_price
        position["peak_unrealized_gain"] = mark.peak_unrealized_gain
        position["trailing_drawdown_pct"] = mark.trailing_drawdown_pct
    report = {
        **metrics,
        "new_holdings_auto_mapped": sync["added"],
        "mapping_failures": sync["failed"],
        "new_catalysts": news["new_catalysts"],
        "developing_catalysts": news["developing_catalysts"],
        "catalyst_calendar": news["catalyst_calendar"],
        "earnings_within_14d": news["earnings_within_14d"],
        "notes": {
            "breakeven": BREAKEVEN_NOTE,
            "maintenance": MAINTENANCE_NOTE,
        },
    }
    _write_json(out_path, report)
    return report


def fetch_history(symbol: str) -> Any:
    """Daily bars for ATR and realized volatility. Used by a live audit only."""
    import yfinance as yf

    frame = yf.Ticker(symbol).history(period="6mo", interval="1d", auto_adjust=False)
    if frame is None or getattr(frame, "empty", True):
        raise LookupError(f"no daily history for {symbol}")
    return frame


def _load_market(
    symbols: set[str], history_fetcher: HistoryFetcher
) -> tuple[dict[str, float | None], dict[str, float | None], dict[str, float | None]]:
    sigmas: dict[str, float | None] = {}
    atrs: dict[str, float | None] = {}
    closes: dict[str, float | None] = {}
    for symbol in sorted(symbols):
        try:
            frame = history_fetcher(symbol)
        except Exception:
            sigmas[symbol] = None
            atrs[symbol] = None
            closes[symbol] = None
            continue
        sigmas[symbol] = _sigma_from_frame(frame)
        atrs[symbol] = _atr_from_frame(frame)
        closes[symbol] = _last_close(frame)
    return sigmas, atrs, closes


def _market_symbols(held: list[str], portfolio_map: Mapping[str, Any]) -> set[str]:
    symbols = set(held)
    for ticker in held:
        meta = portfolio_map.get(ticker) or {}
        symbols.update(underlying_candidates(ticker, meta))
    return symbols


def _sigma_from_frame(frame: Any) -> float | None:
    try:
        closes = _series(frame, "close")
        return realized_daily_volatility(closes)
    except (ValueError, KeyError, TypeError):
        return None


def _atr_from_frame(frame: Any) -> float | None:
    try:
        return wilder_atr(
            _series(frame, "high"),
            _series(frame, "low"),
            _series(frame, "close"),
        )
    except (ValueError, KeyError, TypeError):
        return None


def _last_close(frame: Any) -> float | None:
    try:
        closes = _series(frame, "close")
    except (KeyError, TypeError):
        return None
    return closes[-1] if closes else None


def _series(frame: Any, name: str) -> list[float]:
    columns = {str(column).lower(): column for column in frame.columns}
    if name not in columns:
        raise KeyError(name)
    return [float(value) for value in frame[columns[name]].tolist()]


def _primary_positions(book: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    from src.quant_engine import select_primary_account

    account = select_primary_account(book)
    return list(account.get("positions") or [])


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
