"""Regression coverage for market marks and the broker snapshot."""

from datetime import datetime, timezone

from src.desk import _mark_book_market_quotes, _metrics


def _book():
    return {
        "as_of": "2026-01-01T00:00:00+00:00",
        "accounts": [{
            "role": "primary",
            "cash": -1000.0,
            "total_value": 4120.0,
            "positions": [
                {"ticker": "RAM", "shares": 1000, "current_price": 5, "market_value": 5000},
                {"ticker": "UBRL", "shares": 10, "current_price": 12, "market_value": 120},
            ],
        }],
    }


def test_mark_book_updates_only_newer_quotes():
    book = _book()
    status = _mark_book_market_quotes(book, lambda _: {
        "RAM": (6.5, datetime(2026, 1, 2, tzinfo=timezone.utc)),
        "UBRL": (10, datetime(2025, 12, 31, tzinfo=timezone.utc)),
    })

    assert status["updated"] == ["RAM"]
    assert status["unchanged"] == ["UBRL"]
    assert status["latest_as_of"] == "2026-01-02T00:00:00+00:00"
    assert book["as_of"] == "2026-01-01T00:00:00+00:00"
    assert book["accounts"][0]["total_value"] == 5620.0


def test_audit_cache_cannot_supply_stale_holdings(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    (data / "latest_audit.json").write_text(
        '{"positions": [{"ticker": "SOLD", "current_price": 9}]}'
    )
    metrics, _ = _metrics(tmp_path, _book(), {})
    assert {row["ticker"]: row["current_price"] for row in metrics["positions"]} == {
        "RAM": 5, "UBRL": 12,
    }
