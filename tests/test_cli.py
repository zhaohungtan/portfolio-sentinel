"""Smoke command and an offline audit that writes the JSON payload."""

from __future__ import annotations

import json
from pathlib import Path

from src.cli import main, run_audit, run_smoke

ROOT = Path(__file__).resolve().parents[1]


def test_smoke_passes() -> None:
    summary = run_smoke(ROOT)
    assert summary["ram_look_through"] > 0
    assert summary["korea_samsung"] > 0
    assert main(["smoke"]) == 0


def test_audit_writes_payload_without_network(tmp_path) -> None:
    book_src = json.loads((ROOT / "data/fixtures/sample_book.json").read_text())
    book_src["accounts"][0]["positions"].append(
        {
            "ticker": "XYZ",
            "asset_class": "equity",
            "shares": 10,
            "avg_cost": 20.0,
            "current_price": 18.0,
            "market_value": 180.0,
        }
    )
    book_path = tmp_path / "live_book.json"
    book_path.write_text(json.dumps(book_src))
    map_path = tmp_path / "portfolio_map.json"
    map_path.write_text((ROOT / "portfolio_map.json").read_text())

    def history(symbol: str):
        import pandas as pd

        close = [100.0 + i for i in range(40)]
        return pd.DataFrame(
            {
                "High": [price + 1 for price in close],
                "Low": [price - 1 for price in close],
                "Close": close,
            }
        )

    def profiles(symbol: str) -> dict:
        assert symbol == "XYZ"
        return {
            "quoteType": "EQUITY",
            "longName": "Example Corp",
            "sector": "Industrials",
            "industry": "Specialty Industrial Machinery",
            "earnings_dates": ["2026-12-01"],
        }

    def headlines(symbol: str) -> list[dict]:
        if symbol != "MU":
            return []
        return [
            {
                "title": "Micron earnings outlook steady",
                "publisher": "Desk",
                "url": None,
                "published_at": "2026-11-22T20:00:00-08:00",
            }
        ]

    report = run_audit(
        book_path,
        map_path,
        tmp_path / "sentinel.duckdb",
        tmp_path / "latest_audit.json",
        profile_fetcher=profiles,
        history_fetcher=history,
        news_fetcher=headlines,
    )
    assert report["new_holdings_auto_mapped"][0]["ticker"] == "XYZ"
    assert any(row["ticker"] == "XYZ" for row in report["positions"])
    assert report["new_catalysts"][0]["ticker"] == "MU"
    assert report["earnings_within_14d"][0]["ticker"] == "XYZ"
    written = json.loads((tmp_path / "latest_audit.json").read_text())
    assert written["positions"][0]["peak_price"] > 0
    saved = json.loads(map_path.read_text())
    assert saved["RAM"]["leverage"] == 2.0
    assert saved["XYZ"]["mapping_status"] == "auto"
