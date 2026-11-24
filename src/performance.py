"""Point-in-time and multi-day strategy stats. Short history stays null."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

import duckdb

from src.constants import GOLD_INTEREST_FREE_USD, GOLD_MARGIN_APR

TRADING_DAYS = 252


def summarize_performance(
    equity_points: Sequence[tuple[datetime, float]],
    *,
    margin_used: float,
    unrealized_pnl: float | None,
    daily_decay_drag: float,
    benchmarks: Mapping[str, Sequence[tuple[datetime, float]]] | None = None,
    fills: Sequence[Mapping[str, Any]] | None = None,
    position_drawdown: float | None = None,
) -> dict[str, Any]:
    """TWR needs two snapshot days. One day still reports carry and P&L."""
    ordered = sorted(equity_points, key=lambda item: item[0])
    span_days = 0
    if len(ordered) >= 2:
        span_days = max((ordered[-1][0].date() - ordered[0][0].date()).days, 0)
    daily_gold = _daily_gold(margin_used)
    trades = closed_trade_stats(list(fills or []))
    curve: list[dict[str, Any]] = []
    peak = ordered[0][1] if ordered else 0.0
    for point in ordered:
        peak = max(peak, float(point[1]))
        curve.append(
            {
                "date": point[0].date().isoformat(),
                "net_equity": float(point[1]),
                "high_water": peak,
            }
        )
    result: dict[str, Any] = {
        "track_record": "ok" if len(ordered) >= 2 else "insufficient snapshot history",
        "twr": None,
        "daily_returns": [],
        "sharpe": None,
        "sortino": None,
        "max_drawdown": None,
        "worst_position_drawdown": position_drawdown,
        "alpha_smh": None,
        "alpha_qqq": None,
        "alpha_spy": None,
        "benchmark_twr": {},
        "equity_curve": curve,
        "unrealized_pnl": unrealized_pnl,
        "daily_gold_carry": daily_gold,
        "daily_decay_drag": float(daily_decay_drag),
        "cumulative_gold_carry": daily_gold * span_days,
        "cumulative_decay_drag": float(daily_decay_drag) * span_days,
        "cumulative_drag": (daily_gold + float(daily_decay_drag)) * span_days,
        "win_rate": trades["win_rate"],
        "profit_factor": trades["profit_factor"],
        "closed_trades": trades["closed_trades"],
        "point_in_time": len(ordered) < 2,
    }
    if len(ordered) < 2:
        return result
    returns = [
        ordered[i][1] / ordered[i - 1][1] - 1.0
        for i in range(1, len(ordered))
        if ordered[i - 1][1] > 0
    ]
    if not returns:
        result["track_record"] = "insufficient snapshot history"
        result["point_in_time"] = True
        return result
    twr = _product(returns) - 1.0
    result["twr"] = twr
    result["daily_returns"] = returns
    result["sharpe"] = _sharpe(returns)
    result["sortino"] = _sortino(returns)
    result["max_drawdown"] = _max_drawdown([point[1] for point in ordered])
    benches = benchmarks or {}
    for symbol in ("SMH", "QQQ", "SPY"):
        bench = _benchmark_twr(ordered, benches.get(symbol) or [])
        result["benchmark_twr"][symbol] = bench
        if symbol in {"SMH", "QQQ", "SPY"} and bench is not None:
            result[f"alpha_{symbol.lower()}"] = twr - bench
    return result


def closed_trade_stats(fills: list[Mapping[str, Any]]) -> dict[str, Any]:
    """FIFO round trips. An empty journal is null, not a 0% win rate."""
    if not fills:
        return {"win_rate": None, "profit_factor": None, "closed_trades": 0}
    lots: dict[str, list[list[float]]] = {}
    pnls: list[float] = []
    ordered = sorted(fills, key=lambda row: str(row.get("executed_at") or ""))
    for fill in ordered:
        symbol = str(fill["symbol"])
        side = str(fill["side"]).lower()
        qty = float(fill["quantity"])
        price = float(fill["price"])
        book = lots.setdefault(symbol, [])
        if side == "buy":
            book.append([qty, price])
            continue
        if side != "sell":
            continue
        remaining = qty
        while remaining > 1e-9 and book:
            lot_qty, lot_price = book[0]
            taken = min(remaining, lot_qty)
            pnls.append((price - lot_price) * taken)
            lot_qty -= taken
            remaining -= taken
            if lot_qty <= 1e-9:
                book.pop(0)
            else:
                book[0][0] = lot_qty
    if not pnls:
        return {"win_rate": None, "profit_factor": None, "closed_trades": 0}
    wins = [value for value in pnls if value > 0]
    losses = [value for value in pnls if value < 0]
    gross_loss = abs(sum(losses))
    return {
        "win_rate": len(wins) / len(pnls),
        "profit_factor": None if gross_loss == 0 else sum(wins) / gross_loss,
        "closed_trades": len(pnls),
    }


def read_performance(
    db_path: Path,
    *,
    benchmarks: Mapping[str, Sequence[tuple[datetime, float]]] | None = None,
    unrealized_pnl: float | None = None,
    daily_decay_drag: float = 0.0,
    margin_used: float | None = None,
) -> dict[str, Any]:
    path = Path(db_path)
    if not path.exists():
        return summarize_performance(
            [],
            margin_used=0.0 if margin_used is None else margin_used,
            unrealized_pnl=unrealized_pnl,
            daily_decay_drag=daily_decay_drag,
            benchmarks=benchmarks,
            fills=[],
        )
    conn = duckdb.connect(str(path), read_only=True)
    try:
        points = _equity_points(conn)
        margin = _latest_margin(conn)
        if margin == 0.0 and margin_used:
            margin = margin_used
        drawdown = _worst_position_drawdown(conn)
        fills = _journal_rows(conn)
    finally:
        conn.close()
    return summarize_performance(
        points,
        margin_used=margin,
        unrealized_pnl=unrealized_pnl,
        daily_decay_drag=daily_decay_drag,
        benchmarks=benchmarks,
        fills=fills,
        position_drawdown=drawdown,
    )


def load_trade_journal(db_path: Path, journal_path: Path | None) -> int:
    """Replace the local fill table from a JSON file the agent can drop in."""
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fills: list[dict[str, Any]] = []
    if journal_path is not None and Path(journal_path).exists():
        payload = json.loads(Path(journal_path).read_text(encoding="utf-8"))
        fills = list(payload if isinstance(payload, list) else payload.get("fills") or [])
    conn = duckdb.connect(str(path))
    try:
        _ensure_trade_journal(conn)
        conn.execute("DELETE FROM trade_journal")
        if fills:
            conn.executemany(
                """
                INSERT INTO trade_journal (
                    fill_id, symbol, side, quantity, price, executed_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        str(row["fill_id"]),
                        str(row["symbol"]),
                        str(row["side"]),
                        float(row["quantity"]),
                        float(row["price"]),
                        str(row["executed_at"]),
                    )
                    for row in fills
                ],
            )
        return len(fills)
    finally:
        conn.close()


def fetch_benchmark_levels(start: str, end: str) -> dict[str, list[dict[str, Any]]]:
    """Daily adjusted prices for SMH, QQQ, and SPY."""
    import yfinance as yf

    frame = yf.download(
        ["SMH", "QQQ", "SPY"],
        start=start,
        end=end,
        auto_adjust=True,
        progress=False,
    )
    close = frame["Close"] if "Close" in getattr(frame, "columns", []) else frame
    out: dict[str, list[dict[str, Any]]] = {}
    for symbol in ("SMH", "QQQ", "SPY"):
        series = close[symbol] if symbol in getattr(close, "columns", []) else None
        if series is None:
            out[symbol] = []
            continue
        rows = []
        for stamp, value in series.dropna().items():
            day = stamp.date().isoformat() if hasattr(stamp, "date") else str(stamp)[:10]
            rows.append({"date": day, "close": float(value)})
        out[symbol] = rows
    return out


def _ensure_trade_journal(conn: duckdb.DuckDBPyConnection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS trade_journal (
            fill_id VARCHAR PRIMARY KEY,
            symbol VARCHAR,
            side VARCHAR,
            quantity DOUBLE,
            price DOUBLE,
            executed_at VARCHAR
        )
        """
    )


def _equity_points(conn: duckdb.DuckDBPyConnection) -> list[tuple[datetime, float]]:
    try:
        rows = conn.execute(
            """
            SELECT snapshot_ts, max(net_equity)
            FROM daily_snapshots
            GROUP BY snapshot_ts
            ORDER BY snapshot_ts
            """
        ).fetchall()
    except duckdb.CatalogException:
        return []
    return [(row[0], float(row[1])) for row in rows]


def _latest_margin(conn: duckdb.DuckDBPyConnection) -> float:
    try:
        row = conn.execute(
            """
            SELECT margin_used FROM daily_snapshots
            ORDER BY snapshot_ts DESC LIMIT 1
            """
        ).fetchone()
    except duckdb.CatalogException:
        return 0.0
    return 0.0 if row is None else float(row[0])


def _worst_position_drawdown(conn: duckdb.DuckDBPyConnection) -> float | None:
    try:
        row = conn.execute(
            "SELECT max(trailing_drawdown_pct) FROM high_water_marks"
        ).fetchone()
    except duckdb.CatalogException:
        return None
    if row is None or row[0] is None:
        return None
    return float(row[0])


def _journal_rows(conn: duckdb.DuckDBPyConnection) -> list[dict[str, Any]]:
    try:
        rows = conn.execute(
            """
            SELECT fill_id, symbol, side, quantity, price, executed_at
            FROM trade_journal
            ORDER BY executed_at
            """
        ).fetchall()
    except duckdb.CatalogException:
        return []
    return [
        {
            "fill_id": row[0],
            "symbol": row[1],
            "side": row[2],
            "quantity": row[3],
            "price": row[4],
            "executed_at": row[5],
        }
        for row in rows
    ]


RECONSTRUCTED_LABEL = "reconstructed from current shares"


def reconstruct_equity(
    positions: Sequence[Mapping[str, Any]],
    cash: float,
    closes: Mapping[str, Sequence[tuple[datetime, float]]],
    *,
    sessions: int = 30,
) -> list[tuple[datetime, float]]:
    """Current shares times each close, plus today's cash.

    The series is a what-if path, not broker history, and is never written
    into daily_snapshots.
    """
    priced: dict[str, list[tuple[datetime, float]]] = {}
    for position in positions:
        ticker = str(position.get("ticker") or "")
        series = sorted(closes.get(ticker) or [], key=lambda item: item[0])
        if series:
            priced[ticker] = series
    if not priced:
        return []
    dates = [stamp for stamp, _price in max(priced.values(), key=len)][-sessions:]
    curve: list[tuple[datetime, float]] = []
    for day in dates:
        equity = float(cash)
        for position in positions:
            ticker = str(position.get("ticker") or "")
            price = _price_asof(priced.get(ticker) or [], day)
            if price is None:
                continue
            shares = position.get("shares")
            if shares is None or shares == "":
                current = float(position.get("current_price") or 0.0)
                market_value = float(position.get("market_value") or 0.0)
                shares = market_value / current if current else 0.0
            equity += float(shares) * price
        curve.append((day, equity))
    return curve


def download_closes(symbols: Sequence[str]) -> dict[str, list[tuple[datetime, float]]]:
    """Daily closes for a reconstruction. A failed symbol is skipped."""
    import yfinance as yf
    from datetime import timezone

    found: dict[str, list[tuple[datetime, float]]] = {}
    for symbol in symbols:
        try:
            frame = yf.Ticker(symbol).history(period="3mo", auto_adjust=True, interval="1d")
        except Exception:
            continue
        if frame is None or getattr(frame, "empty", True) or "Close" not in getattr(frame, "columns", []):
            continue
        rows: list[tuple[datetime, float]] = []
        for stamp, value in frame["Close"].dropna().items():
            day = stamp.to_pydatetime() if hasattr(stamp, "to_pydatetime") else stamp
            if not isinstance(day, datetime):
                continue
            if day.tzinfo is None:
                day = day.replace(tzinfo=timezone.utc)
            rows.append((day, float(value)))
        if rows:
            found[str(symbol)] = rows
    return found


def _price_asof(series: Sequence[tuple[datetime, float]], day: datetime) -> float | None:
    found: float | None = None
    for stamp, price in series:
        if stamp.date() <= day.date():
            found = float(price)
            continue
        break
    return found


def _daily_gold(margin_used: float) -> float:
    bearing = max(0.0, float(margin_used) - GOLD_INTEREST_FREE_USD)
    return bearing * GOLD_MARGIN_APR / 365.0


def _product(returns: Sequence[float]) -> float:
    value = 1.0
    for item in returns:
        value *= 1.0 + item
    return value


def _sharpe(returns: Sequence[float]) -> float | None:
    if len(returns) < 2:
        return None
    import numpy as np

    arr = np.asarray(returns, dtype=float)
    std = float(arr.std(ddof=1))
    if std == 0:
        return None
    return float(arr.mean() / std * np.sqrt(TRADING_DAYS))


def _sortino(returns: Sequence[float]) -> float | None:
    if len(returns) < 2:
        return None
    import numpy as np

    arr = np.asarray(returns, dtype=float)
    downside = arr[arr < 0]
    if len(downside) == 0:
        return None
    std = float(downside.std(ddof=1)) if len(downside) > 1 else float(abs(downside[0]))
    if std == 0:
        return None
    return float(arr.mean() / std * np.sqrt(TRADING_DAYS))


def _max_drawdown(equity: Sequence[float]) -> float | None:
    peak = equity[0]
    worst = 0.0
    if peak <= 0:
        return None
    for value in equity:
        peak = max(peak, value)
        if peak > 0:
            worst = min(worst, value / peak - 1.0)
    return abs(worst)


def _benchmark_twr(
    equity: Sequence[tuple[datetime, float]],
    prices: Sequence[tuple[datetime, float]],
) -> float | None:
    if not prices:
        return None
    start = equity[0][0].date()
    end = equity[-1][0].date()
    ordered = sorted(prices, key=lambda item: item[0])
    start_px = None
    end_px = None
    for stamp, price in ordered:
        if stamp.date() <= start:
            start_px = price
        if stamp.date() <= end:
            end_px = price
    if start_px is None:
        start_px = ordered[0][1]
    if end_px is None or start_px <= 0:
        return None
    return end_px / start_px - 1.0
