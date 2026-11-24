"""DuckDB snapshot and high-water behavior."""

from __future__ import annotations

from datetime import datetime, timezone

from src.db import SentinelDB, SnapshotRow


def _row(price: float, *, when: datetime | None = None) -> SnapshotRow:
    return SnapshotRow(
        snapshot_ts=when or datetime(2026, 11, 22, tzinfo=timezone.utc),
        ticker="RAM",
        shares=10.0,
        avg_cost=6.0,
        current_price=price,
        market_value=price * 10.0,
        margin_used=450.00,
        net_equity=2540.00,
    )


def test_high_water_keeps_peak_and_records_drawdown(tmp_path) -> None:
    with SentinelDB(tmp_path / "sentinel.duckdb") as db:
        first = db.record_book([_row(10.0)])
        assert first["RAM"].peak_price == 10.0
        assert first["RAM"].peak_unrealized_gain == 40.0
        assert first["RAM"].trailing_drawdown_pct == 0.0
        later = datetime(2026, 11, 23, tzinfo=timezone.utc)
        second = db.record_book([_row(8.0, when=later)])
        assert second["RAM"].peak_price == 10.0
        assert second["RAM"].peak_unrealized_gain == 40.0
        assert second["RAM"].trailing_drawdown_pct == 20.0
        assert db.snapshot_count() == 2
