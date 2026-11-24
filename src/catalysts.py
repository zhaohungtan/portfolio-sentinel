"""Macro calendar merged with mapped company catalysts."""

from __future__ import annotations

import json
import math
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Mapping
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
MACRO_PATH = ROOT / "data" / "macro_calendar.json"
LA = ZoneInfo("America/Los_Angeles")
NY = ZoneInfo("America/New_York")
MU_DATE = "2026-12-17"
MU_WEIGHT = 0.2616


def load_macro(path: Path | None = None) -> list[dict[str, Any]]:
    payload = json.loads((path or MACRO_PATH).read_text(encoding="utf-8"))
    return list(payload.get("events") or [])


def implied_move(
    sigma_daily: float | None,
    days: int,
    leverage: float,
    *,
    option_move: float | None = None,
) -> dict[str, Any]:
    """± move. Option straddle wins; otherwise a 95% vol-scaled range."""
    if option_move is not None:
        return {
            "move_pct": abs(float(option_move)) * float(leverage),
            "source": "option-straddle",
        }
    if sigma_daily is None or days < 0:
        return {"move_pct": None, "source": None}
    horizon = max(days, 1) / 252.0
    return {
        "move_pct": 1.96 * float(sigma_daily) * math.sqrt(horizon) * float(leverage),
        "source": "vol-scaled",
    }


def build_calendar(
    portfolio_map: Mapping[str, Any],
    positions: list[Mapping[str, Any]],
    as_of: datetime,
    sigmas: Mapping[str, float | None] | None = None,
    *,
    option_moves: Mapping[str, float] | None = None,
    macro_events: list[Mapping[str, Any]] | None = None,
    radar_days: int = 30,
) -> dict[str, Any]:
    today = _calendar_today(as_of)
    vol = sigmas or {}
    options = option_moves or {}
    from src.quant_engine import is_active_position

    by_ticker = {
        str(row.get("ticker")): row for row in positions if is_active_position(row)
    }
    events: list[dict[str, Any]] = []
    book_value = _look_through(list(by_ticker.values()))
    book_sigma = _book_sigma(positions, vol)
    for raw in macro_events if macro_events is not None else load_macro():
        event_day = date.fromisoformat(str(raw["date"]))
        remaining = (event_day - today).days
        if _event_has_passed(event_day, raw.get("time_et"), as_of):
            continue
        move = implied_move(book_sigma, 1, 1.0)
        events.append(
            {
                "date": event_day.isoformat(),
                "time_et": raw.get("time_et"),
                "name": raw.get("name"),
                "kind": "macro",
                "ticker": None,
                "held_ticker": None,
                "days_remaining": remaining,
                "exposure_usd": book_value,
                "weight": None,
                "highlighted": False,
                "implied_move_pct": move["move_pct"],
                "implied_move_source": move["source"],
            }
        )
    for ticker, meta in portfolio_map.items():
        if str(ticker) not in by_ticker:
            continue
        catalyst = meta.get("next_major_catalyst") or {}
        if not catalyst.get("date"):
            continue
        event_day = date.fromisoformat(str(catalyst["date"]))
        remaining = (event_day - today).days
        if _event_has_passed(event_day, None, as_of):
            continue
        held = by_ticker.get(str(ticker), {})
        leverage = float(meta.get("leverage") or held.get("leverage") or 1.0)
        sigma = _position_sigma(str(ticker), meta, vol)
        weight = _event_weight(str(catalyst.get("ticker") or ""), meta)
        exposure = float(held.get("market_value") or 0.0) * (weight if weight is not None else 1.0)
        if leverage > 1.0 and weight is not None:
            exposure = float(held.get("look_through_usd") or (float(held.get("market_value") or 0.0) * leverage)) * weight
        move = implied_move(
            sigma,
            remaining,
            leverage,
            option_move=options.get(str(catalyst.get("ticker") or ticker)),
        )
        highlighted = str(catalyst.get("date")) == MU_DATE and str(catalyst.get("ticker")) == "MU"
        event_name = catalyst.get("event")
        if highlighted:
            event_name = "MU (Micron) Q1 FY27 Earnings"
        events.append(
            {
                "date": event_day.isoformat(),
                "time_et": None,
                "name": event_name,
                "kind": "company",
                "ticker": catalyst.get("ticker"),
                "held_ticker": ticker,
                "days_remaining": remaining,
                "exposure_usd": exposure,
                "weight": MU_WEIGHT if highlighted else weight,
                "highlighted": highlighted,
                "implied_move_pct": move["move_pct"],
                "implied_move_source": move["source"],
            }
        )
    events.sort(key=lambda row: (row["days_remaining"], 0 if row["kind"] == "macro" else 1))
    upcoming = [row for row in events if row["days_remaining"] >= 0]
    radar_end = today + timedelta(days=radar_days)
    radar = [
        row
        for row in upcoming
        if date.fromisoformat(row["date"]) <= radar_end
    ]
    return {"next": upcoming[0] if upcoming else None, "radar": radar, "all": upcoming}


def _calendar_today(now: datetime) -> date:
    if now.tzinfo is None:
        return now.date()
    return now.astimezone(LA).date()


def _event_has_passed(event_day: date, time_et: str | None, now: datetime) -> bool:
    today = _calendar_today(now)
    if event_day < today:
        return True
    if event_day > today or not time_et:
        return False
    hour, minute = (int(part) for part in str(time_et).split(":")[:2])
    event_at = datetime(event_day.year, event_day.month, event_day.day, hour, minute, tzinfo=NY)
    current = now if now.tzinfo else now.replace(tzinfo=NY)
    return current.astimezone(NY) >= event_at


def _look_through(positions: list[Mapping[str, Any]]) -> float:
    total = 0.0
    for row in positions:
        if row.get("look_through_usd") is not None:
            total += float(row["look_through_usd"])
            continue
        total += float(row.get("market_value") or 0.0) * float(row.get("leverage") or 1.0)
    return total


def _book_sigma(
    positions: list[Mapping[str, Any]], sigmas: Mapping[str, float | None]
) -> float | None:
    total = 0.0
    weighted = 0.0
    for row in positions:
        value = float(row.get("market_value") or 0.0)
        sigma = row.get("sigma_daily")
        if sigma is None:
            sigma = sigmas.get(str(row.get("underlying_symbol") or row.get("ticker")))
        if value <= 0 or sigma is None:
            continue
        total += value
        weighted += value * float(sigma) * float(row.get("leverage") or 1.0)
    if total <= 0:
        return None
    return weighted / total


def _position_sigma(
    ticker: str, meta: Mapping[str, Any], sigmas: Mapping[str, float | None]
) -> float | None:
    from src.quant_engine import underlying_candidates

    for symbol in underlying_candidates(ticker, meta):
        value = sigmas.get(symbol)
        if value is not None:
            return float(value)
    return None


def _event_weight(news_ticker: str, meta: Mapping[str, Any]) -> float | None:
    from src.quant_engine import news_ticker_weight

    if not news_ticker:
        return None
    return news_ticker_weight(meta, news_ticker)
