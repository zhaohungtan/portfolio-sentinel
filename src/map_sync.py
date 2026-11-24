"""Append holdings that are in the live book and missing from the map."""

from __future__ import annotations

import json
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any, Callable, Mapping

from src.quant_engine import is_active_position, select_primary_account

ProfileFetcher = Callable[[str], Mapping[str, Any]]

_SKIP_TOKENS = {
    "ETF",
    "ETN",
    "ETP",
    "USD",
    "THE",
    "AND",
    "DAILY",
    "TARGET",
    "LONG",
    "SHORT",
    "BULL",
    "BEAR",
    "ULTRA",
    "ULTRAPRO",
    "SHARES",
    "GRANITESHARES",
    "DIREXION",
    "DEFIANCE",
    "ROUNDHILL",
    "TRADR",
    "PROSHARES",
    "TREX",
}
_AI_NEEDLES = (
    "semiconductor",
    "software infrastructure",
    "software-infrastructure",
    "data center",
    "data-center",
    "datacenter",
)


def load_map(path: Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def save_map(path: Path, portfolio_map: Mapping[str, Any]) -> None:
    destination = Path(path)
    payload = json.dumps(portfolio_map, indent=2) + "\n"
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.write_text(payload, encoding="utf-8")
    temporary.replace(destination)


def active_equity_tickers(book: Mapping[str, Any]) -> list[str]:
    primary = select_primary_account(book)
    tickers: list[str] = []
    for position in primary.get("positions") or []:
        if str(position.get("asset_class") or "equity") != "equity":
            continue
        if not is_active_position(position):
            continue
        tickers.append(str(position["ticker"]).upper())
    return tickers


def infer_leverage(name: str, quote_type: str | None = None) -> float:
    if quote_type and quote_type.upper() in {"EQUITY", "CRYPTOCURRENCY"}:
        return 1.0
    match = re.search(r"(?i)\b([23])\s*x\b", name or "")
    if match:
        return float(match.group(1))
    match = re.search(r"(?i)bull\s*([23])\s*x", name or "")
    if match:
        return float(match.group(1))
    if re.search(r"(?i)daily\s+target", name or ""):
        return 2.0
    return 1.0


def infer_news_tickers(symbol: str, name: str, leverage: float) -> list[str]:
    if leverage == 1.0:
        return [symbol]
    long_match = re.search(r"\bLong\s+([A-Z]{1,5})\b", name or "")
    if long_match and long_match.group(1) not in _SKIP_TOKENS:
        return [long_match.group(1)]
    bull_match = re.search(r"\b([A-Z]{1,5})\s+Bull\b", name or "")
    if bull_match and bull_match.group(1) not in _SKIP_TOKENS:
        return [bull_match.group(1)]
    for token in re.findall(r"\b[A-Z]{1,5}\b", name or ""):
        if token not in _SKIP_TOKENS and token != symbol:
            return [token]
    return [symbol]


def infer_sector_cluster(profile: Mapping[str, Any]) -> str:
    blob = " ".join(
        str(profile.get(key) or "")
        for key in ("sector", "industry", "category", "longName")
    ).lower()
    if any(needle in blob for needle in _AI_NEEDLES):
        return "AI_Infrastructure"
    sector = str(profile.get("sector") or "Unknown")
    slug = re.sub(r"[^A-Za-z0-9]+", "_", sector).strip("_")
    return slug or "Unknown"


def next_earnings_date(dates: list[str] | None, today: date) -> date | None:
    upcoming: list[date] = []
    for raw in dates or []:
        try:
            day = date.fromisoformat(str(raw)[:10])
        except ValueError:
            continue
        if day >= today:
            upcoming.append(day)
    return min(upcoming) if upcoming else None


def build_entry(
    symbol: str, profile: Mapping[str, Any], *, mapped_on: date
) -> dict[str, Any]:
    name = str(profile.get("longName") or symbol)
    quote_type = profile.get("quoteType")
    quote_text = str(quote_type) if quote_type else None
    leverage = infer_leverage(name, quote_text)
    news = infer_news_tickers(symbol, name, leverage)
    entry: dict[str, Any] = {
        "name": name,
        "leverage": leverage,
        "news_tickers": news,
        "sector_cluster": infer_sector_cluster(profile),
        "mapping_status": "auto",
        "auto_mapped_at": mapped_on.isoformat(),
        "quote_type": quote_text,
    }
    catalyst_day = next_earnings_date(
        list(profile.get("earnings_dates") or []), mapped_on
    )
    if catalyst_day is not None:
        entry["next_major_catalyst"] = {
            "ticker": news[0],
            "event": "Earnings",
            "date": catalyst_day.isoformat(),
        }
    return entry


def sync_missing(
    book: Mapping[str, Any],
    map_path: Path,
    profile_fetcher: ProfileFetcher,
    *,
    today: date | None = None,
) -> dict[str, Any]:
    """Append missing equity tickers. Existing keys are not rewritten."""
    mapped_on = today or _book_date(book)
    portfolio_map = load_map(map_path)
    added: list[dict[str, Any]] = []
    failed: list[dict[str, str]] = []
    for ticker in active_equity_tickers(book):
        if ticker in portfolio_map:
            continue
        try:
            profile = profile_fetcher(ticker)
            entry = build_entry(ticker, profile, mapped_on=mapped_on)
        except Exception as exc:  # yfinance and network failures stay in the audit
            failed.append({"ticker": ticker, "error": str(exc)})
            continue
        portfolio_map[ticker] = entry
        added.append({"ticker": ticker, "entry": entry})
    if added:
        save_map(map_path, portfolio_map)
    return {"added": added, "failed": failed, "map": portfolio_map}


def fetch_profile(symbol: str) -> dict[str, Any]:
    """yfinance metadata used only by a live audit, never by the smoke test."""
    import yfinance as yf

    ticker = yf.Ticker(symbol)
    info: dict[str, Any] = {}
    try:
        info = dict(ticker.info or {})
    except Exception:
        info = {}
    summary: dict[str, Any] = {}
    try:
        raw_summary = getattr(ticker, "summary_detail", None)
        if isinstance(raw_summary, dict):
            summary = raw_summary
    except Exception:
        summary = {}
    earnings = _earnings_dates(ticker)
    return {
        "quoteType": info.get("quoteType"),
        "longName": info.get("longName") or info.get("shortName") or symbol,
        "sector": info.get("sector"),
        "industry": info.get("industry"),
        "category": info.get("category") or summary.get("category"),
        "summaryDetail": summary,
        "earnings_dates": earnings,
    }


def _earnings_dates(ticker: Any) -> list[str]:
    try:
        try:
            frame = ticker.get_earnings_dates(limit=12)
        except TypeError:
            frame = ticker.get_earnings_dates()
    except Exception:
        return []
    if frame is None or getattr(frame, "empty", True):
        return []
    found: list[str] = []
    for index in frame.index:
        day = index.date() if hasattr(index, "date") else index
        if isinstance(day, datetime):
            day = day.date()
        if isinstance(day, date):
            found.append(day.isoformat())
    return found


def _book_date(book: Mapping[str, Any]) -> date:
    raw = book.get("as_of")
    if not raw:
        return date.today()
    return datetime.fromisoformat(str(raw)).date()
