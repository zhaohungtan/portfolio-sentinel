"""Offline checks for leverage math and the Nov 22 fixture."""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from src.quant_engine import (
    build_metrics,
    daily_variance_drag,
    gold_carry,
    look_through,
    maintenance_excess_estimated,
    realized_daily_volatility,
    required_underlying_rally,
    stop_limit_trigger,
    underlying_candidates,
    wilder_atr,
)

ROOT = Path(__file__).resolve().parents[1]


def test_two_x_drag_equals_variance() -> None:
    sigma = 0.02
    assert daily_variance_drag(2.0, sigma) == pytest.approx(sigma**2)
    assert daily_variance_drag(1.0, sigma) == 0.0


def test_break_even_rally_adds_drag_then_divides_by_leverage() -> None:
    rally = required_underlying_rally(6.33, 4.09, 2.0, 0.0004, 30)
    etf_gap = 6.33 / 4.09 - 1.0
    assert rally == pytest.approx((etf_gap + 0.0004 * 30) / 2.0)
    assert required_underlying_rally(10.0, 12.0, 2.0, 0.01, 30) == 0.0
    flat = required_underlying_rally(10.0, 8.0, 1.0, 0.0, 60)
    assert flat == pytest.approx(10.0 / 8.0 - 1.0)


def test_wilder_atr_and_stop() -> None:
    close = [10.0] * 14
    high = [11.0] * 14
    low = [9.0] * 14
    assert wilder_atr(high, low, close) == pytest.approx(2.0)
    assert stop_limit_trigger(4.09, 0.40) == pytest.approx(3.49)


def test_realized_vol_of_alternating_returns() -> None:
    closes = [100.0]
    for i in range(30):
        closes.append(closes[-1] * math.exp(0.01 if i % 2 == 0 else -0.01))
    sigma = realized_daily_volatility(closes, 30)
    assert sigma == pytest.approx(math.sqrt(30 * 0.0001 / 29))


def test_fixture_look_through_korea_and_cluster() -> None:
    book = json.loads((ROOT / "data/fixtures/sample_book.json").read_text())
    portfolio_map = json.loads((ROOT / "portfolio_map.json").read_text())
    sigmas = {symbol: 0.02 for symbol in ("DRAM", "MU", "UBER", "NFLX", "SMCI", "NBIS", "APLD", "MP", "VST", "NVDA")}
    atrs = {ticker: 1.0 for ticker in portfolio_map}
    metrics = build_metrics(book, portfolio_map, sigmas=sigmas, atrs=atrs)
    ram = next(row for row in metrics["positions"] if row["ticker"] == "RAM")
    assert ram["look_through_usd"] == pytest.approx(look_through(2400.00, 2.0))
    assert metrics["korea_overnight_gap"]["samsung_usd"] == pytest.approx(2400.00 * 2.0 * 0.2825)
    assert metrics["korea_overnight_gap"]["sk_hynix_usd"] == pytest.approx(2400.00 * 2.0 * 0.2330)
    assert ram["daily_variance_drag"] == pytest.approx(0.0004)
    assert ram["underlying_symbol"] == "DRAM"
    assert ram["days_to_catalyst"] == 25
    assert ram["within_14_days"] is False
    assert metrics["cluster"]["market_value"] == pytest.approx(3420.00)
    assert metrics["cluster"]["weight"] == pytest.approx(3420.00 / 3990.00)
    assert "SOL" not in {row["ticker"] for row in metrics["positions"]}
    assert metrics["dust_positions"][0]["ticker"] == "SOL"
    carry = gold_carry(-1450.00)
    assert carry["interest_bearing_balance"] == pytest.approx(450.00)
    assert carry["annual_interest_carry"] == pytest.approx(450.00 * 0.0525)
    assert metrics["margin"]["maintenance_excess"] is None
    assert metrics["margin"]["maintenance_excess_estimated"] == pytest.approx(
        maintenance_excess_estimated(2540.00, 3990.00)
    )


def test_sigma_falls_back_from_dram_to_mu() -> None:
    book = json.loads((ROOT / "data/fixtures/sample_book.json").read_text())
    portfolio_map = json.loads((ROOT / "portfolio_map.json").read_text())
    assert underlying_candidates("RAM", portfolio_map["RAM"]) == ["DRAM", "MU"]
    sigmas = {"DRAM": None, "MU": 0.03}
    atrs = {"RAM": 0.5}
    tiny = {
        "as_of": book["as_of"],
        "accounts": [
            {
                **book["accounts"][0],
                "positions": [book["accounts"][0]["positions"][0]],
            }
        ],
    }
    metrics = build_metrics(tiny, portfolio_map, sigmas=sigmas, atrs=atrs)
    ram = metrics["positions"][0]
    assert ram["underlying_symbol"] == "MU"
    assert ram["sigma_daily"] == pytest.approx(0.03)
    assert ram["sigma_note"] == "fallback from DRAM"
    assert ram["stop_limit_trigger"] == pytest.approx(12.00 - 1.5 * 0.5)
