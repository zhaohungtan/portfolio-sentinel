"""Dollar break-even, the ATR floor, what-if books, and the short-history curve."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.desk import _with_reconstruction, margin_scenarios
from src.quant_engine import (
    annotate_position_impact,
    build_metrics,
    stop_is_vol_capped,
    stop_limit_trigger,
)

ROOT = Path(__file__).resolve().parents[1]


def test_stop_floor_keeps_nebx_positive_and_the_old_ram_level() -> None:
    assert stop_limit_trigger(2.74, 3.0) == pytest.approx(2.74 * 0.70)
    assert stop_is_vol_capped(2.74, 3.0) is True
    assert stop_limit_trigger(4.09, 0.40) == pytest.approx(3.49)
    assert stop_is_vol_capped(4.09, 0.40) is False


def test_ram_break_even_dollars_and_signals() -> None:
    book = json.loads((ROOT / "data/fixtures/sample_book.json").read_text())
    portfolio_map = json.loads((ROOT / "portfolio_map.json").read_text())
    sigmas = {"DRAM": 0.02, "UBER": 0.02, "NBIS": 0.02, "APLD": 0.02}
    atrs = {"RAM": 0.40, "NEBX": 3.0, "UBRL": 0.2, "APLD": 0.5}
    metrics = build_metrics(
        book,
        portfolio_map,
        sigmas=sigmas,
        atrs=atrs,
        last_closes={"DRAM": 20.0, "UBER": 60.0},
    )
    ram = next(row for row in metrics["positions"] if row["ticker"] == "RAM")
    assert ram["cost_basis"] == pytest.approx(17 * 200)
    assert ram["breakeven_gain_usd"] == pytest.approx(ram["cost_basis"] - ram["market_value"])
    assert ram["equity_if_breakeven"] == pytest.approx(2540.00 + ram["breakeven_gain_usd"])
    assert ram["clears_margin"] is True
    assert ram["signal"] == "CORE DRIVER"
    assert ram["underlying_price"] == pytest.approx(20.0)
    assert ram["underlying_target_30d"] == pytest.approx(20.0 * (1.0 + ram["breakeven_underlying_30d"]))

    ubrl = next(row for row in metrics["positions"] if row["ticker"] == "UBRL")
    assert ubrl["signal"] == "NEAR BE"
    assert ubrl["underlying_target_30d"] == pytest.approx(60.0 * (1.0 + ubrl["breakeven_underlying_30d"]))
    apld = next(row for row in metrics["positions"] if row["ticker"] == "APLD")
    assert apld["signal"] == "1X HOLD"
    nebx = next(row for row in metrics["positions"] if row["ticker"] == "NEBX")
    assert nebx["signal"] == "HIGH DECAY"
    assert nebx["vol_capped"] is True
    assert nebx["stop_limit_trigger"] == pytest.approx(6.00 * 0.70)
    assert nebx["clears_margin"] is False


def test_what_if_books_pay_down_debt_without_changing_net_equity() -> None:
    positions = [
        {"ticker": "RAM", "market_value": 2_400.00, "leverage": 2.0, "sigma_daily": 0.02, "sector_cluster": "AI_Infrastructure"},
        {"ticker": "NEBX", "market_value": 270.0, "leverage": 2.0, "sigma_daily": 0.03, "sector_cluster": "AI_Infrastructure"},
        {"ticker": "SMCX", "market_value": 300.0, "leverage": 2.0, "sigma_daily": 0.03, "sector_cluster": "AI_Infrastructure"},
        {"ticker": "APLD", "market_value": 450.0, "leverage": 1.0, "sigma_daily": 0.02, "sector_cluster": "AI_Infrastructure"},
    ]
    net = 2_540.00
    gross = 2_400.00 + 270.0 + 300.0 + 450.0
    margin = 1_450.00
    scenarios = {
        row["id"]: row
        for row in margin_scenarios(positions, net_equity=net, gross=gross, margin_used=margin, n_paths=200)
    }
    trim = scenarios["trim_ram"]
    assert trim["net_equity"] == pytest.approx(net)
    assert trim["margin_used"] == pytest.approx(margin - 2_400.00 * 0.5)
    assert trim["gross_holdings"] == pytest.approx(gross - 2_400.00 * 0.5)
    assert trim["buffer_usd"] == pytest.approx(net - 0.5 * trim["gross_holdings"])
    closed = scenarios["close_nebx_smcx"]
    assert closed["margin_used"] == pytest.approx(margin - 270.0 - 300.0)
    assert closed["net_equity"] == pytest.approx(net)
    zero = scenarios["zero_margin"]
    assert zero["margin_used"] == 0.0
    assert zero["net_equity"] == pytest.approx(net + margin)
    assert zero["gross_holdings"] == pytest.approx(gross)
    assert zero["daily_gold"] == 0.0
    assert zero["stressed_5d"] == 0.0
    assert zero["stressed_21d"] == 0.0


def test_fewer_than_five_snapshot_days_uses_the_reconstructed_curve(tmp_path: Path) -> None:
    cache = {
        "as_of": "2026-11-22T23:46:37-08:00",
        "label": "reconstructed from current shares",
        "equity_curve": [
            {"date": "2026-10-01", "net_equity": 100.0},
            {"date": "2026-10-02", "net_equity": 110.0},
            {"date": "2026-10-03", "net_equity": 105.0},
        ],
        "smh": [],
    }
    data = tmp_path / "data"
    data.mkdir()
    (data / "reconstructed_equity.json").write_text(json.dumps(cache), encoding="utf-8")
    short = {
        "equity_curve": [
            {"date": "2026-11-21", "net_equity": 6100.0},
            {"date": "2026-11-22", "net_equity": 2540.0},
        ]
    }
    rebuilt = _with_reconstruction(
        tmp_path,
        [],
        -100.0,
        short,
        margin_used=100.0,
        unrealized_pnl=0.0,
        daily_decay_drag=0.0,
        book_as_of=cache["as_of"],
    )
    assert rebuilt["track_record"] == "reconstructed from current shares"
    assert len(rebuilt["equity_curve"]) == 3
    long_curve = {
        "equity_curve": [
            {"date": f"2026-11-{day:02d}", "net_equity": 100.0 + day} for day in range(1, 6)
        ]
    }
    kept = _with_reconstruction(
        tmp_path,
        [],
        -100.0,
        long_curve,
        margin_used=100.0,
        unrealized_pnl=0.0,
        daily_decay_drag=0.0,
        book_as_of="2099-01-01T00:00:00-08:00",
    )
    assert kept is long_curve


def test_annotate_is_safe_when_average_cost_is_missing() -> None:
    rows = [{"ticker": "SOL", "shares": 1.0, "avg_cost": None, "current_price": 70.0, "market_value": 70.0, "leverage": 1.0}]
    annotate_position_impact(rows, net_equity=100.0, margin_used=0.0)
    assert rows[0]["cost_basis"] is None
    assert rows[0]["breakeven_gain_usd"] is None
    assert rows[0]["signal"] == "1X HOLD"
    assert rows[0]["underlying_target_30d"] is None
