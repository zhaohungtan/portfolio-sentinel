"""Macro dates merge with mapped earnings, including MU on Dec 17."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from src.catalysts import build_calendar, implied_move

ROOT = Path(__file__).resolve().parents[1]


def test_next_event_and_mu_highlight() -> None:
    portfolio_map = json.loads((ROOT / "portfolio_map.json").read_text())
    as_of = datetime.fromisoformat("2026-11-22T22:48:00-08:00")
    positions = [
        {
            "ticker": "RAM",
            "market_value": 2_400.00,
            "look_through_usd": 4_800.00,
            "leverage": 2.0,
            "sigma_daily": 0.02,
            "news_tickers": portfolio_map["RAM"]["news_tickers"],
            "top_weights": portfolio_map["RAM"]["top_weights"],
        }
    ]
    calendar = build_calendar(portfolio_map, positions, as_of, {"DRAM": 0.02, "MU": 0.02})
    assert calendar["next"]["name"] == "JOLTS Job Openings (Oct)"
    assert calendar["next"]["days_remaining"] == 9
    mu = next(
        row
        for row in calendar["all"]
        if row["ticker"] == "MU" and row["date"] == "2026-12-17"
    )
    assert mu["highlighted"] is True
    assert mu["weight"] == 0.2616
    assert mu["days_remaining"] == 25
    assert mu["implied_move_source"] == "vol-scaled"
    radar_names = {row["name"] for row in calendar["radar"]}
    assert "CPI Inflation Report (Nov)" in radar_names
    assert "PCE Inflation & Q3 Final GDP" not in radar_names


def test_past_events_leave_the_radar() -> None:
    as_of = datetime.fromisoformat("2026-12-01T11:30:00-05:00")
    calendar = build_calendar(
        {},
        [],
        as_of,
        macro_events=[
            {"date": "2026-11-30", "time_et": "10:00", "name": "Yesterday"},
            {"date": "2026-12-01", "time_et": "10:00", "name": "Already printed"},
            {"date": "2026-12-01", "time_et": "14:00", "name": "Still ahead"},
        ],
    )
    names = {row["name"] for row in calendar["radar"]}
    assert "Yesterday" not in names
    assert "Already printed" not in names
    assert names == {"Still ahead"}
    assert calendar["next"]["days_remaining"] == 0


def test_option_straddle_beats_the_vol_fallback() -> None:
    scaled = implied_move(0.02, 25, 2.0)
    listed = implied_move(0.02, 25, 2.0, option_move=0.08)
    assert scaled["source"] == "vol-scaled"
    assert listed["source"] == "option-straddle"
    assert listed["move_pct"] == 0.16
