"""Lexicon polarity and a 7-day window tag."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from src.db import SentinelDB
from src.news_sentiment import curate_tape, persist_scores, score_headline, score_items, sentiment_gauges


def test_lexicon_tags() -> None:
    assert score_headline("Micron earnings beat and raised guidance") == ("POSITIVE", 1.0)
    assert score_headline("Regulator opens a probe") == ("NEGATIVE", -1.0)
    assert score_headline("Shares were mixed in afternoon trading") == ("NEUTRAL", 0.0)
    assert score_headline("Asian tech back in the firing line as traders track Wall St rout") == ("NEGATIVE", -1.0)
    assert score_headline("Nvidia falls 48% from its peak") == ("NEGATIVE", -1.0)
    assert score_headline("Micron stock plunges 13% as the selloff deepens") == ("NEGATIVE", -1.0)
    assert score_headline("David Tepper's Micron bet raises a question") == ("NEUTRAL", 0.0)
    assert score_headline("Is Netflix a Buy in November? The Bull and Bear Cases.") == ("NEUTRAL", 0.0)


def test_curate_keeps_named_stories_once() -> None:
    rows = curate_tape(
        [
            {
                "ticker": "NVDA",
                "held_tickers": ["NVDA"],
                "title": "If You'd Bought Oklo at Its SPAC Debut",
                "url": "https://example.test/oklo",
                "published_at": "2026-11-23T07:35:00+00:00",
                "polarity": "NEUTRAL",
                "sentiment": 0.0,
                "scope": "COMPANY",
                "exposure_usd": 5.0,
            },
            {
                "ticker": "005930.KS",
                "held_tickers": ["RAM"],
                "title": "Samsung and SK Hynix slide as the memory selloff deepens",
                "url": "https://example.test/samsung",
                "published_at": "2026-11-23T07:24:00+00:00",
                "polarity": "NEUTRAL",
                "sentiment": 0.0,
                "scope": "COMPANY",
                "exposure_usd": 100.0,
            },
            {
                "ticker": "000660.KS",
                "held_tickers": ["RAM"],
                "title": "Samsung and SK Hynix slide as the memory selloff deepens",
                "url": "https://example.test/hynix",
                "published_at": "2026-11-23T07:24:00+00:00",
                "polarity": "NEUTRAL",
                "sentiment": 0.0,
                "scope": "COMPANY",
                "exposure_usd": 80.0,
            },
        ]
    )
    assert len(rows) == 1
    assert rows[0]["polarity"] == "NEGATIVE"
    assert rows[0]["ticker"] == "005930.KS"
    assert rows[0]["held_tickers"] == ["RAM"]


def test_windows_and_persist_do_not_drop_the_headline(tmp_path) -> None:
    now = datetime(2026, 11, 22, 22, tzinfo=timezone.utc)
    rows = score_items(
        [
            {
                "ticker": "MU",
                "title": "Micron earnings beat",
                "published_at": now - timedelta(hours=3),
            },
            {
                "ticker": "SPY",
                "title": "Index futures plunge",
                "published_at": now - timedelta(days=2),
                "scope": "MACRO",
            },
        ],
        [
            {
                "ticker": "RAM",
                "look_through_usd": 1_000.0,
                "news_tickers": ["MU"],
                "top_weights": {"MU": 0.25},
            }
        ],
        now=now,
    )
    assert rows[0]["windows"] == ["24H", "72H", "7D"]
    assert "24H" not in rows[1]["windows"]
    assert rows[1]["scope"] == "MACRO"
    gauges = sentiment_gauges(rows)
    assert gauges["portfolio_24h"] == 1.0
    assert gauges["macro_72h"] == -1.0
    with SentinelDB(tmp_path / "sentinel.duckdb") as db:
        persist_scores(db, rows, now)
        stored = db.conn.execute(
            "SELECT polarity, sentiment, scope FROM catalyst_log ORDER BY ticker"
        ).fetchall()
    assert ("NEGATIVE", -1.0, "MACRO") in [(row[0], row[1], row[2]) for row in stored]
