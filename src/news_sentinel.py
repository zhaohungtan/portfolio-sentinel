"""48-hour headlines, deduped against the catalyst log."""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Mapping

from src.constants import EARNINGS_ALARM_DAYS, NEWS_LOOKBACK_HOURS
from src.db import SentinelDB
from src.quant_engine import news_ticker_weight

NewsFetcher = Callable[[str], list[Mapping[str, Any]]]

_RULES: list[tuple[re.Pattern[str], float]] = [
    (re.compile(r"\b(earnings|eps|guidance|outlook)\b", re.I), 0.90),
    (re.compile(r"\b(halt|halted|sec|doj|lawsuit|regulator|regulatory|probe)\b", re.I), 0.85),
    (re.compile(r"\b(beat|miss|offering|dilution|bankruptcy)\b", re.I), 0.75),
    (re.compile(r"\b(downgrade|upgrade|price target|initiates)\b", re.I), 0.70),
]
_KOREA_TICKERS = {"005930.KS", "000660.KS"}


def headline_hash(ticker: str, headline: str) -> str:
    """SHA-256 of the ticker plus a whitespace-normalized headline."""
    normalized = " ".join(headline.strip().lower().split())
    processed = f"{ticker}|{normalized}"
    return hashlib.sha256(processed.encode("utf-8")).hexdigest()


def materiality_score(headline: str, ticker: str) -> float:
    score = 0.20
    for pattern, weight in _RULES:
        if pattern.search(headline):
            score = max(score, weight)
    if ticker in _KOREA_TICKERS:
        score = min(1.0, max(score + 0.10, 0.45))
    return round(score, 2)


def normalize_news_item(raw: Mapping[str, Any]) -> dict[str, Any] | None:
    content = raw.get("content")
    if isinstance(content, dict):
        title = content.get("title")
        published = content.get("pubDate") or content.get("displayTime")
        provider = content.get("provider") or {}
        publisher = provider.get("displayName") if isinstance(provider, dict) else None
        url = content.get("canonicalUrl") or content.get("clickThroughUrl")
        if isinstance(url, dict):
            url = url.get("url")
    else:
        title = raw.get("title")
        published = raw.get("providerPublishTime")
        publisher = raw.get("publisher")
        url = raw.get("link")
    if not title:
        return None
    published_at = _parse_time(published)
    if published_at is None:
        return None
    return {
        "title": str(title),
        "publisher": publisher,
        "url": url,
        "published_at": published_at,
    }


def expanded_news_tickers(portfolio_map: Mapping[str, Any], held: list[str]) -> list[str]:
    ordered: list[str] = []
    for ticker in held:
        meta = portfolio_map.get(ticker) or {}
        for symbol in meta.get("news_tickers") or [ticker]:
            text = str(symbol)
            if text not in ordered:
                ordered.append(text)
    return ordered


def catalyst_calendar(
    positions: list[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    calendar: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for position in positions:
        catalyst = position.get("next_major_catalyst")
        if not isinstance(catalyst, dict) or not catalyst.get("date"):
            continue
        key = (str(catalyst.get("ticker")), str(catalyst.get("date")))
        if key in seen:
            continue
        seen.add(key)
        days = position.get("days_to_catalyst")
        calendar.append(
            {
                "held_ticker": position.get("ticker"),
                "ticker": catalyst.get("ticker"),
                "event": catalyst.get("event"),
                "date": catalyst.get("date"),
                "days_remaining": days,
                "within_14_days": days is not None and 0 <= int(days) <= EARNINGS_ALARM_DAYS,
            }
        )
    calendar.sort(key=lambda row: (row["days_remaining"] is None, row["days_remaining"]))
    return calendar


def exposure_usd(news_ticker: str, positions: list[Mapping[str, Any]]) -> float:
    total = 0.0
    for position in positions:
        meta = {
            "ticker": position.get("ticker"),
            "news_tickers": position.get("news_tickers") or [],
            "top_weights": position.get("top_weights") or {},
        }
        weight = news_ticker_weight(meta, news_ticker)
        total += float(position.get("look_through_usd") or 0.0) * weight
    return total


def ingest_headlines(
    db: SentinelDB,
    items: list[Mapping[str, Any]],
    positions: list[Mapping[str, Any]],
    *,
    now: datetime,
    lookback_hours: int = NEWS_LOOKBACK_HOURS,
) -> dict[str, list[dict[str, Any]]]:
    """Return new headlines and ones already stored that showed up again."""
    window_start = now - timedelta(hours=lookback_hours)
    fresh: list[dict[str, Any]] = []
    developing: list[dict[str, Any]] = []
    for item in items:
        published = item.get("published_at")
        if not isinstance(published, datetime):
            continue
        if published.tzinfo is None:
            published = published.replace(tzinfo=timezone.utc)
        current = now if now.tzinfo else now.replace(tzinfo=timezone.utc)
        if published < window_start or published > current + timedelta(minutes=5):
            continue
        ticker = str(item["ticker"])
        title = str(item["title"])
        digest = headline_hash(ticker, title)
        exposure = exposure_usd(ticker, positions)
        score = materiality_score(title, ticker)
        payload = {
            "ticker": ticker,
            "title": title,
            "publisher": item.get("publisher"),
            "url": item.get("url"),
            "published_at": published.isoformat(),
            "headline_hash": digest,
            "materiality": score,
            "exposure_usd": exposure,
            "priority": score * exposure,
        }
        if db.has_headline(digest):
            db.touch_headline(digest, current)
            developing.append(payload)
            continue
        db.insert_headline(digest, ticker, title, score, current)
        fresh.append(payload)
    fresh.sort(key=lambda row: float(row["priority"]), reverse=True)
    developing.sort(key=lambda row: float(row["priority"]), reverse=True)
    return {"new_catalysts": fresh, "developing_catalysts": developing}


def collect_news(
    portfolio_map: Mapping[str, Any],
    positions: list[Mapping[str, Any]],
    db: SentinelDB,
    news_fetcher: NewsFetcher,
    *,
    now: datetime,
) -> dict[str, Any]:
    held = [str(position["ticker"]) for position in positions]
    items: list[dict[str, Any]] = []
    for symbol in expanded_news_tickers(portfolio_map, held):
        for raw in news_fetcher(symbol):
            parsed = _coerce_news_item(raw)
            if parsed is None:
                continue
            parsed["ticker"] = symbol
            items.append(parsed)
    ingested = ingest_headlines(db, items, positions, now=now)
    calendar = catalyst_calendar(positions)
    return {
        **ingested,
        "catalyst_calendar": calendar,
        "earnings_within_14d": [row for row in calendar if row["within_14_days"]],
    }


def fetch_news(symbol: str) -> list[dict[str, Any]]:
    """Pull yfinance headlines. Items without a publish time are dropped."""
    import yfinance as yf

    raw_items = yf.Ticker(symbol).news or []
    found: list[dict[str, Any]] = []
    for raw in raw_items:
        if not isinstance(raw, dict):
            continue
        normalized = normalize_news_item(raw)
        if normalized is None:
            continue
        found.append(normalized)
    return found


def _coerce_news_item(raw: Mapping[str, Any]) -> dict[str, Any] | None:
    if not isinstance(raw, Mapping):
        return None
    if raw.get("title") and raw.get("published_at") is not None:
        parsed = dict(raw)
        published = parsed.get("published_at")
        if not isinstance(published, datetime):
            parsed["published_at"] = _parse_time(published)
        if parsed.get("published_at") is None:
            return None
        return parsed
    return normalize_news_item(raw)


def _parse_time(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value), tz=timezone.utc)
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
