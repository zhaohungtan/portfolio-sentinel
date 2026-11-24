"""Local DuckDB state for snapshots, peaks, and seen headlines."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import duckdb


@dataclass(frozen=True)
class SnapshotRow:
    snapshot_ts: datetime
    ticker: str
    shares: float
    avg_cost: float | None
    current_price: float
    market_value: float
    margin_used: float
    net_equity: float


@dataclass(frozen=True)
class HighWater:
    ticker: str
    peak_price: float
    peak_unrealized_gain: float | None
    trailing_drawdown_pct: float
    updated_ts: datetime


class SentinelDB:
    """Append-only daily book plus mutable peaks and catalyst hashes."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = duckdb.connect(str(self.path))
        self._ensure_schema()

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> SentinelDB:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _ensure_schema(self) -> None:
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS daily_snapshots (
                snapshot_ts TIMESTAMPTZ,
                ticker VARCHAR,
                shares DOUBLE,
                avg_cost DOUBLE,
                current_price DOUBLE,
                market_value DOUBLE,
                margin_used DOUBLE,
                net_equity DOUBLE
            )
            """
        )
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS high_water_marks (
                ticker VARCHAR PRIMARY KEY,
                peak_price DOUBLE,
                peak_unrealized_gain DOUBLE,
                trailing_drawdown_pct DOUBLE,
                updated_ts TIMESTAMPTZ
            )
            """
        )
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS catalyst_log (
                headline_hash VARCHAR PRIMARY KEY,
                ticker VARCHAR,
                headline VARCHAR,
                materiality DOUBLE,
                first_seen_ts TIMESTAMPTZ,
                last_seen_ts TIMESTAMPTZ,
                sentiment DOUBLE,
                polarity VARCHAR,
                scope VARCHAR,
                exposure_usd DOUBLE
            )
            """
        )
        for name, column_type in (
            ("sentiment", "DOUBLE"),
            ("polarity", "VARCHAR"),
            ("scope", "VARCHAR"),
            ("exposure_usd", "DOUBLE"),
        ):
            self.conn.execute(
                f"ALTER TABLE catalyst_log ADD COLUMN IF NOT EXISTS {name} {column_type}"
            )

    def insert_snapshots(self, rows: list[SnapshotRow]) -> None:
        if not rows:
            return
        self.conn.executemany(
            """
            INSERT INTO daily_snapshots (
                snapshot_ts, ticker, shares, avg_cost, current_price,
                market_value, margin_used, net_equity
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    row.snapshot_ts,
                    row.ticker,
                    row.shares,
                    row.avg_cost,
                    row.current_price,
                    row.market_value,
                    row.margin_used,
                    row.net_equity,
                )
                for row in rows
            ],
        )

    def update_high_water(self, row: SnapshotRow) -> HighWater:
        """Raise the peak when price or unrealized gain makes a new high.

        Trailing drawdown is the percent decline from the peak price.
        """
        unrealized = _unrealized(row.current_price, row.avg_cost, row.shares)
        existing = self.conn.execute(
            """
            SELECT peak_price, peak_unrealized_gain
            FROM high_water_marks
            WHERE ticker = ?
            """,
            [row.ticker],
        ).fetchone()
        if existing is None:
            peak_price = row.current_price
            peak_unrealized = unrealized
        else:
            peak_price = max(float(existing[0]), row.current_price)
            prior_unrealized = existing[1]
            if unrealized is None:
                peak_unrealized = (
                    None if prior_unrealized is None else float(prior_unrealized)
                )
            elif prior_unrealized is None:
                peak_unrealized = unrealized
            else:
                peak_unrealized = max(float(prior_unrealized), unrealized)
        drawdown = _drawdown_pct(peak_price, row.current_price)
        self.conn.execute("DELETE FROM high_water_marks WHERE ticker = ?", [row.ticker])
        self.conn.execute(
            """
            INSERT INTO high_water_marks (
                ticker, peak_price, peak_unrealized_gain,
                trailing_drawdown_pct, updated_ts
            ) VALUES (?, ?, ?, ?, ?)
            """,
            [row.ticker, peak_price, peak_unrealized, drawdown, row.snapshot_ts],
        )
        return HighWater(
            ticker=row.ticker,
            peak_price=peak_price,
            peak_unrealized_gain=peak_unrealized,
            trailing_drawdown_pct=drawdown,
            updated_ts=row.snapshot_ts,
        )

    def record_book(self, rows: list[SnapshotRow]) -> dict[str, HighWater]:
        self.insert_snapshots(rows)
        return {row.ticker: self.update_high_water(row) for row in rows}

    def has_headline(self, headline_hash: str) -> bool:
        found = self.conn.execute(
            "SELECT 1 FROM catalyst_log WHERE headline_hash = ?",
            [headline_hash],
        ).fetchone()
        return found is not None

    def insert_headline(
        self,
        headline_hash: str,
        ticker: str,
        headline: str,
        materiality: float,
        seen_at: datetime,
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO catalyst_log (
                headline_hash, ticker, headline, materiality,
                first_seen_ts, last_seen_ts
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            [headline_hash, ticker, headline, materiality, seen_at, seen_at],
        )

    def annotate_headline(
        self,
        headline_hash: str,
        sentiment: float,
        polarity: str,
        scope: str,
        exposure_usd: float,
    ) -> None:
        """Attach sentiment fields. insert_headline itself stays unchanged."""
        self.conn.execute(
            """
            UPDATE catalyst_log
            SET sentiment = ?, polarity = ?, scope = ?, exposure_usd = ?
            WHERE headline_hash = ?
            """,
            [sentiment, polarity, scope, exposure_usd, headline_hash],
        )

    def touch_headline(self, headline_hash: str, seen_at: datetime) -> None:
        self.conn.execute(
            """
            UPDATE catalyst_log
            SET last_seen_ts = ?
            WHERE headline_hash = ?
            """,
            [seen_at, headline_hash],
        )

    def snapshot_count(self) -> int:
        row = self.conn.execute("SELECT count(*) FROM daily_snapshots").fetchone()
        return int(row[0]) if row else 0


def _unrealized(
    price: float, avg_cost: float | None, shares: float
) -> float | None:
    if avg_cost is None:
        return None
    return (price - avg_cost) * shares


def _drawdown_pct(peak_price: float, current_price: float) -> float:
    if peak_price <= 0:
        return 0.0
    return (peak_price - current_price) / peak_price * 100.0
