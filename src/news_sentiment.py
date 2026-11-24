"""Seven-day macro and company headline polarity.

Scores are a fixed lexicon, not a model. The same headline always gets the
same tag, which is what the tests lock.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any, Mapping, Sequence

from src.db import SentinelDB
from src.news_sentinel import headline_hash
from src.quant_engine import news_ticker_weight

POSITIVE = re.compile(
    r"\b(?:beats?|rais(?:e|ed|es)|upgrades?|upgraded|surges?|surged|rall(?:y|ies|ied)|"
    r"jumps?|jumped|gains?|gained|soars?|soared|rebounds?|rebounded|buybacks?|"
    r"outperform(?:s|ed)?|upside|rips?)\b",
    re.I,
)
NEGATIVE = re.compile(
    r"\b(?:miss(?:es|ed)?|downgrades?|downgraded|halts?|halted|probes?|lawsuits?|"
    r"plung(?:e|es|ed)|routs?|slumps?|slumped|crash(?:es|ed)?|sell-?offs?|"
    r"sinks?|sank|sunk|tumbl(?:e|es|ed)|warnings?|warns|warned|drops?|dropped|"
    r"falls?|fell|slides?|slid|slips?|slipped|worst|losses|loss|cuts?|fears?|"
    r"bears?|bearish|lowest|52-week lows?)\b",
    re.I,
)
_NOT_A_RAISE = re.compile(r"\brais(?:e|ed|es)\s+a\b[^.?]{0,48}\bquestion\b", re.I)
_NOT_A_BEAR = re.compile(r"\bbear cases?\b", re.I)
_SUBJECTS: dict[str, tuple[str, ...]] = {
    "MU": ("micron",),
    "005930.KS": ("samsung",),
    "000660.KS": ("sk hynix", "hynix"),
    "STX": ("seagate",),
    "WDC": ("western digital",),
    "SNDK": ("sandisk",),
    "UBER": ("uber",),
    "NFLX": ("netflix",),
    "SMCI": ("super micro", "supermicro"),
    "APLD": ("applied digital",),
    "MP": ("mp materials",),
    "VST": ("vistra",),
    "NBIS": ("nebius",),
    "NVDA": ("nvidia", "nvda"),
    "SPY": ("s&p", "spy", "wall street", "wall st", "stock market"),
    "QQQ": ("nasdaq", "qqq"),
    "TLT": ("treasury", "treasuries", "tlt", "fed"),
    "SOXX": ("semiconductor", "soxx", "chip stock", "chip index"),
}
MACRO_PROXIES = ("SPY", "QQQ", "TLT", "SOXX")
WINDOWS = {"24H": 24, "72H": 72, "7D": 24 * 7}


def score_headline(title: str) -> tuple[str, float]:
    text = _NOT_A_BEAR.sub(" ", _NOT_A_RAISE.sub(" ", title))
    positives = len(POSITIVE.findall(text))
    negatives = len(NEGATIVE.findall(text))
    if positives > negatives:
        return "POSITIVE", 1.0
    if negatives > positives:
        return "NEGATIVE", -1.0
    return "NEUTRAL", 0.0


def mentions_subject(title: str, ticker: str) -> bool:
    """True when the headline names the company or the macro market it was filed under."""
    text = title.lower()
    for alias in _SUBJECTS.get(ticker, ()):
        if alias in text:
            return True
    symbol = ticker.split(".")[0]
    if len(symbol) >= 4 and re.search(rf"\b{re.escape(symbol.lower())}\b", text):
        return True
    return False


def curate_tape(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Drop headlines that never name the subject, then keep one copy of each story."""
    grouped: dict[str, dict[str, Any]] = {}
    for raw in rows:
        title = str(raw.get("title") or "")
        ticker = str(raw.get("ticker") or "")
        if not title or not mentions_subject(title, ticker):
            continue
        polarity, sentiment = score_headline(title)
        row = dict(raw)
        row["polarity"] = polarity
        row["sentiment"] = sentiment
        row["held_tickers"] = [str(name) for name in (raw.get("held_tickers") or [])]
        key = " ".join(title.lower().split())
        current = grouped.get(key)
        if current is None:
            grouped[key] = row
            continue
        held = list(dict.fromkeys([*current["held_tickers"], *row["held_tickers"]]))
        current["held_tickers"] = held
        if float(row.get("exposure_usd") or 0.0) > float(current.get("exposure_usd") or 0.0):
            current["ticker"] = row["ticker"]
            current["exposure_usd"] = row["exposure_usd"]
            current["scope"] = row.get("scope")
    curated = list(grouped.values())
    curated.sort(key=lambda row: str(row.get("published_at") or ""), reverse=True)
    return curated


def window_labels(published: datetime, now: datetime) -> list[str]:
    age = now - published
    if age < timedelta(0):
        if age < timedelta(minutes=-10):
            return []
        age = timedelta(0)
    labels = []
    for name, hours in WINDOWS.items():
        if age <= timedelta(hours=hours) and age >= timedelta(0):
            labels.append(name)
    return labels


def score_items(
    items: Sequence[Mapping[str, Any]],
    positions: Sequence[Mapping[str, Any]],
    *,
    now: datetime,
) -> list[dict[str, Any]]:
    scored: list[dict[str, Any]] = []
    for raw in items:
        title = str(raw.get("title") or "")
        if not title:
            continue
        published = raw.get("published_at")
        if isinstance(published, str):
            published = datetime.fromisoformat(published)
        if not isinstance(published, datetime):
            continue
        ticker = str(raw.get("ticker") or "")
        polarity, sentiment = score_headline(title)
        scope = "MACRO" if ticker in MACRO_PROXIES or raw.get("scope") == "MACRO" else "COMPANY"
        exposure = 0.0 if scope == "MACRO" else _exposure(ticker, positions)
        held = _held_for(ticker, positions)
        scored.append(
            {
                "ticker": ticker,
                "held_tickers": held,
                "title": title,
                "publisher": raw.get("publisher"),
                "url": raw.get("url"),
                "published_at": published.isoformat(),
                "polarity": polarity,
                "sentiment": sentiment,
                "scope": scope,
                "exposure_usd": exposure,
                "windows": window_labels(published, now),
                "headline_hash": headline_hash(ticker, title),
            }
        )
    scored.sort(key=lambda row: row["published_at"], reverse=True)
    return scored


def persist_scores(db: SentinelDB, rows: Sequence[Mapping[str, Any]], seen_at: datetime) -> None:
    for row in rows:
        digest = str(row["headline_hash"])
        if not db.has_headline(digest):
            db.insert_headline(
                digest,
                str(row["ticker"]),
                str(row["title"]),
                abs(float(row["sentiment"])),
                seen_at,
            )
        db.annotate_headline(
            digest,
            float(row["sentiment"]),
            str(row["polarity"]),
            str(row["scope"]),
            float(row["exposure_usd"]),
        )


def sentiment_gauges(rows: Sequence[Mapping[str, Any]]) -> dict[str, float | None]:
    """Unweighted macro mean, exposure-weighted company mean."""
    gauges: dict[str, float | None] = {}
    for window in WINDOWS:
        macro = [
            float(row["sentiment"])
            for row in rows
            if row.get("scope") == "MACRO" and window in (row.get("windows") or [])
        ]
        company = [
            row
            for row in rows
            if row.get("scope") == "COMPANY" and window in (row.get("windows") or [])
        ]
        gauges[f"macro_{window.lower()}"] = _mean(macro)
        gauges[f"portfolio_{window.lower()}"] = _weighted(company)
    return gauges


def holding_trends(
    rows: Sequence[Mapping[str, Any]], held_tickers: Sequence[str]
) -> dict[str, float | None]:
    trends: dict[str, float | None] = {}
    for ticker in held_tickers:
        matched = [
            row
            for row in rows
            if "7D" in (row.get("windows") or []) and ticker in (row.get("held_tickers") or [])
        ]
        trends[ticker] = _weighted(matched)
    return trends


def _exposure(news_ticker: str, positions: Sequence[Mapping[str, Any]]) -> float:
    total = 0.0
    for position in positions:
        weight = news_ticker_weight(
            {
                "ticker": position.get("ticker"),
                "news_tickers": position.get("news_tickers") or [],
                "top_weights": position.get("top_weights") or {},
            },
            news_ticker,
        )
        total += float(position.get("look_through_usd") or position.get("market_value") or 0.0) * weight
    return total


def _held_for(news_ticker: str, positions: Sequence[Mapping[str, Any]]) -> list[str]:
    held: list[str] = []
    for position in positions:
        news = [str(symbol) for symbol in (position.get("news_tickers") or [])]
        ticker = str(position.get("ticker") or "")
        if news_ticker == ticker or news_ticker in news:
            if ticker and ticker not in held:
                held.append(ticker)
    return held


def _mean(values: Sequence[float]) -> float | None:
    if not values:
        return None
    return float(sum(values) / len(values))


def _weighted(rows: Sequence[Mapping[str, Any]]) -> float | None:
    if not rows:
        return None
    weight = sum(max(float(row.get("exposure_usd") or 0.0), 0.0) for row in rows)
    if weight <= 0:
        return _mean([float(row["sentiment"]) for row in rows])
    return float(
        sum(float(row["sentiment"]) * max(float(row.get("exposure_usd") or 0.0), 0.0) for row in rows)
        / weight
    )
