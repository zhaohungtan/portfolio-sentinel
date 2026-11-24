"""TWR stays null until there are two snapshot days, and an empty journal is null."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.performance import closed_trade_stats, summarize_performance


def _day(iso: str) -> datetime:
    return datetime.fromisoformat(iso).replace(tzinfo=timezone.utc)


def test_one_snapshot_does_not_invent_a_track_record() -> None:
    stats = summarize_performance(
        [(_day("2026-11-22"), 2_540.00)],
        margin_used=1_450.00,
        unrealized_pnl=-1_600.00,
        daily_decay_drag=12.0,
        fills=[],
    )
    assert stats["twr"] is None
    assert stats["sharpe"] is None
    assert stats["alpha_smh"] is None
    assert stats["win_rate"] is None
    assert stats["point_in_time"] is True
    assert stats["unrealized_pnl"] == pytest.approx(-1_600.00)
    assert stats["daily_gold_carry"] == pytest.approx(450.00 * 0.0525 / 365.0)


def test_twr_and_alpha_over_two_days() -> None:
    points = [(_day("2026-11-21"), 100.0), (_day("2026-11-22"), 110.0)]
    benches = {
        "SMH": [(_day("2026-11-21"), 100.0), (_day("2026-11-22"), 105.0)],
        "QQQ": [(_day("2026-11-21"), 100.0), (_day("2026-11-22"), 100.0)],
        "SPY": [(_day("2026-11-21"), 50.0), (_day("2026-11-22"), 51.0)],
    }
    stats = summarize_performance(
        points,
        margin_used=0.0,
        unrealized_pnl=10.0,
        daily_decay_drag=0.0,
        benchmarks=benches,
    )
    assert stats["twr"] == pytest.approx(0.10)
    assert stats["alpha_smh"] == pytest.approx(0.05)
    assert stats["alpha_qqq"] == pytest.approx(0.10)
    assert stats["benchmark_twr"]["SPY"] == pytest.approx(0.02)
    assert stats["alpha_spy"] == pytest.approx(0.08)
    assert stats["max_drawdown"] == pytest.approx(0.0)


def test_empty_journal_is_null_and_round_trips_have_a_win_rate() -> None:
    assert closed_trade_stats([])["win_rate"] is None
    stats = closed_trade_stats(
        [
            {"symbol": "A", "side": "buy", "quantity": 1, "price": 10, "executed_at": "2026-11-01"},
            {"symbol": "A", "side": "sell", "quantity": 1, "price": 12, "executed_at": "2026-11-02"},
            {"symbol": "B", "side": "buy", "quantity": 1, "price": 10, "executed_at": "2026-11-01"},
            {"symbol": "B", "side": "sell", "quantity": 1, "price": 8, "executed_at": "2026-11-03"},
        ]
    )
    assert stats["closed_trades"] == 2
    assert stats["win_rate"] == pytest.approx(0.5)
    assert stats["profit_factor"] == pytest.approx(1.0)
