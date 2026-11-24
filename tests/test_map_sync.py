"""Auto-map inference without calling yfinance."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from src.map_sync import (
    active_equity_tickers,
    build_entry,
    infer_leverage,
    infer_news_tickers,
    infer_sector_cluster,
    sync_missing,
)

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    ("name", "expected_leverage", "expected_ticker"),
    [
        ("Roundhill T-REX 2X Long DRAM Daily Target ETF", 2.0, "DRAM"),
        ("GraniteShares 2x Long UBER Daily ETF", 2.0, "UBER"),
        ("Direxion Daily NFLX Bull 2X ETF", 2.0, "NFLX"),
        ("Defiance Daily Target 2X Long SMCI ETF", 2.0, "SMCI"),
        ("Tradr 2X Long NBIS Daily ETF", 2.0, "NBIS"),
        ("Applied Digital Corporation", 1.0, "APLD"),
    ],
)
def test_leverage_and_underlying(name: str, expected_leverage: float, expected_ticker: str) -> None:
    symbol = "APLD" if expected_leverage == 1.0 else "NEW"
    quote = "EQUITY" if expected_leverage == 1.0 else "ETF"
    leverage = infer_leverage(name, quote)
    assert leverage == expected_leverage
    assert infer_news_tickers(symbol, name, leverage) == [expected_ticker]


def test_sector_cluster_matches_semiconductors_only_when_text_says_so() -> None:
    assert infer_sector_cluster({"industry": "Semiconductors", "sector": "Technology"}) == "AI_Infrastructure"
    assert infer_sector_cluster({"sector": "Consumer Cyclical"}) == "Consumer_Cyclical"


def test_sync_appends_missing_ticker_and_leaves_existing_keys(tmp_path) -> None:
    source = json.loads((ROOT / "portfolio_map.json").read_text())
    map_path = tmp_path / "portfolio_map.json"
    map_path.write_text(json.dumps({"RAM": source["RAM"]}, indent=2) + "\n")
    book = {
        "as_of": "2026-11-22T22:48:00-08:00",
        "accounts": [
            {
                "role": "primary",
                "positions": [
                    {"ticker": "RAM", "asset_class": "equity", "shares": 1, "market_value": 10},
                    {"ticker": "xyz", "asset_class": "equity", "shares": 4, "market_value": 40},
                    {"ticker": "SOL", "asset_class": "crypto", "shares": 0.0000002, "market_value": 0},
                ],
            }
        ],
    }

    def fetcher(symbol: str) -> dict:
        assert symbol == "XYZ"
        return {
            "quoteType": "ETF",
            "longName": "GraniteShares 2x Long ABC Daily ETF",
            "sector": "Technology",
            "industry": "Semiconductors",
            "earnings_dates": ["2026-11-01", "2027-03-01"],
        }

    result = sync_missing(book, map_path, fetcher)
    assert [row["ticker"] for row in result["added"]] == ["XYZ"]
    written = json.loads(map_path.read_text())
    assert written["RAM"]["name"] == source["RAM"]["name"]
    assert written["XYZ"]["leverage"] == 2.0
    assert written["XYZ"]["news_tickers"] == ["ABC"]
    assert written["XYZ"]["sector_cluster"] == "AI_Infrastructure"
    assert written["XYZ"]["mapping_status"] == "auto"
    assert written["XYZ"]["next_major_catalyst"]["date"] == "2027-03-01"
    assert active_equity_tickers(book) == ["RAM", "XYZ"]


def test_failed_profile_does_not_rewrite_the_map(tmp_path) -> None:
    map_path = tmp_path / "portfolio_map.json"
    original = json.dumps({"RAM": {"name": "keep", "leverage": 2.0}}, indent=2) + "\n"
    map_path.write_text(original)
    book = {
        "as_of": "2026-11-22T22:48:00-08:00",
        "accounts": [
            {
                "role": "primary",
                "positions": [
                    {"ticker": "NEW", "asset_class": "equity", "shares": 1, "market_value": 5}
                ],
            }
        ],
    }

    def fetcher(symbol: str) -> dict:
        raise RuntimeError("offline")

    result = sync_missing(book, map_path, fetcher)
    assert result["added"] == []
    assert result["failed"][0]["ticker"] == "NEW"
    assert map_path.read_text() == original


def test_build_entry_uses_quote_type_to_force_single_stock() -> None:
    entry = build_entry(
        "VST",
        {
            "quoteType": "EQUITY",
            "longName": "Vistra Corp.",
            "sector": "Utilities",
            "earnings_dates": [],
        },
        mapped_on=date(2026, 11, 22),
    )
    assert entry["leverage"] == 1.0
    assert entry["news_tickers"] == ["VST"]
    assert "next_major_catalyst" not in entry
