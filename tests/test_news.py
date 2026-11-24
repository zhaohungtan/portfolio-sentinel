"""Headline hashing, materiality, and the 14-day earnings flag."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from src.db import SentinelDB
from src.news_sentinel import (
    catalyst_calendar,
    headline_hash,
    ingest_headlines,
    materiality_score,
    normalize_news_item,
)


def test_repeat_headline_is_not_new(tmp_path) -> None:
    now = datetime(2026, 11, 22, 22, 48, tzinfo=timezone.utc)
    item = {
        "ticker": "MU",
        "title": "Micron earnings guidance raised",
        "publisher": "Wire",
        "url": "https://example.test/mu",
        "published_at": now - timedelta(hours=3),
    }
    positions = [
        {
            "ticker": "RAM",
            "look_through_usd": 1000.0,
            "news_tickers": ["MU"],
            "top_weights": {"MU": 0.25},
        }
    ]
    with SentinelDB(tmp_path / "sentinel.duckdb") as db:
        first = ingest_headlines(db, [item], positions, now=now)
        second = ingest_headlines(db, [item], positions, now=now + timedelta(hours=1))
        assert db.has_headline(headline_hash("MU", item["title"]))
    assert len(first["new_catalysts"]) == 1
    assert first["new_catalysts"][0]["materiality"] == 0.90
    assert first["new_catalysts"][0]["exposure_usd"] == 250.0
    assert second["new_catalysts"] == []
    assert len(second["developing_catalysts"]) == 1


def test_materiality_ranks_korea_above_a_generic_recap() -> None:
    assert materiality_score("shares were mixed in trading", "UBER") == 0.20
    assert materiality_score("shares were mixed in trading", "005930.KS") >= 0.45
    assert materiality_score("regulator opens a probe", "NVDA") == 0.85


def test_stale_headline_is_dropped(tmp_path) -> None:
    now = datetime(2026, 11, 22, tzinfo=timezone.utc)
    item = {
        "ticker": "UBER",
        "title": "Old recap",
        "published_at": now - timedelta(hours=72),
    }
    with SentinelDB(tmp_path / "sentinel.duckdb") as db:
        result = ingest_headlines(db, [item], [], now=now)
    assert result["new_catalysts"] == []


def test_earnings_inside_14_days_are_flagged() -> None:
    calendar = catalyst_calendar(
        [
            {
                "ticker": "RAM",
                "days_to_catalyst": 25,
                "next_major_catalyst": {
                    "ticker": "MU",
                    "event": "Q1 FY27 Earnings",
                    "date": "2026-12-17",
                },
            },
            {
                "ticker": "APLD",
                "days_to_catalyst": 7,
                "next_major_catalyst": {
                    "ticker": "APLD",
                    "event": "Earnings",
                    "date": "2026-11-29",
                },
            },
        ]
    )
    flagged = [row for row in calendar if row["within_14_days"]]
    assert [row["ticker"] for row in flagged] == ["APLD"]
    assert any(row["ticker"] == "MU" and row["within_14_days"] is False for row in calendar)


def test_legacy_and_content_news_shapes() -> None:
    legacy = normalize_news_item(
        {
            "title": "Legacy headline",
            "publisher": "Desk",
            "link": "https://example.test/a",
            "providerPublishTime": 1_763_865_600,
        }
    )
    modern = normalize_news_item(
        {
            "content": {
                "title": "Modern headline",
                "pubDate": "2026-11-22T18:00:00Z",
                "provider": {"displayName": "Desk"},
                "canonicalUrl": {"url": "https://example.test/b"},
            }
        }
    )
    assert legacy is not None and legacy["title"] == "Legacy headline"
    assert modern is not None and modern["publisher"] == "Desk"
    assert normalize_news_item({"title": "no time"}) is None
