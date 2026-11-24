"""Empty book, sold names, dust, the static 50% buffer, and the MU title."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.catalysts import build_calendar
from src.map_sync import infer_leverage
from src.margin_prob import simulate_margin, static_maintenance_buffer
from src.performance import reconstruct_equity
from src.quant_engine import build_metrics

ROOT = Path(__file__).resolve().parents[1]
AS_OF = "2026-11-22T22:48:00-08:00"


def _book(positions: list[dict], *, cash: float = -1450.00, total: float = 2540.00) -> dict:
    return {
        "as_of": AS_OF,
        "accounts": [
            {
                "role": "primary",
                "account_mask": "0000",
                "account_type": "individual",
                "is_default": True,
                "is_agentic": False,
                "cash": cash,
                "total_value": total,
                "positions": positions,
            }
        ],
    }


def test_empty_book_skips_numpy_and_keeps_cash(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("numpy path")

    monkeypatch.setattr("src.margin_prob.np.linalg.cholesky", boom)
    result = simulate_margin([], margin_used=1_450.00)
    assert result["probabilities"]["1"] == {"baseline": 0.0, "stressed": 0.0}
    assert result["probabilities"]["5"]["stressed"] == 0.0
    assert result["probabilities"]["21"]["baseline"] == 0.0

    metrics = build_metrics(_book([]), {}, sigmas={}, atrs={})
    assert metrics["positions"] == []
    assert metrics["cluster"]["weight"] == 0.0
    assert metrics["cluster"]["market_value"] == 0.0
    assert metrics["korea_overnight_gap"]["combined_usd"] == 0.0
    assert metrics["margin"]["cash"] == pytest.approx(-1450.00)
    assert metrics["margin"]["net_equity"] == pytest.approx(2540.00)


def test_sold_ram_drops_mu_and_korea() -> None:
    portfolio_map = json.loads((ROOT / "portfolio_map.json").read_text())
    sold = {
        "ticker": "RAM",
        "asset_class": "equity",
        "shares": 0,
        "avg_cost": 6.33,
        "current_price": 4.09,
        "market_value": 2_400.00,
    }
    metrics = build_metrics(_book([sold]), portfolio_map, sigmas={"DRAM": 0.02}, atrs={})
    assert metrics["positions"] == []
    assert metrics["korea_overnight_gap"]["combined_usd"] == 0.0
    calendar = build_calendar(
        portfolio_map,
        [sold],
        datetime.fromisoformat(AS_OF),
        {"MU": 0.02},
    )
    assert all(row.get("ticker") != "MU" for row in calendar["all"])


def test_dust_under_one_dollar_stays_out_of_the_book() -> None:
    dust = {
        "ticker": "TINY",
        "asset_class": "equity",
        "shares": 2,
        "avg_cost": 0.2,
        "current_price": 0.2,
        "market_value": 0.4,
    }
    metrics = build_metrics(_book([dust], cash=100.0, total=100.4), {}, sigmas={}, atrs={})
    assert metrics["positions"] == []
    assert metrics["dust_positions"][0]["ticker"] == "TINY"
    assert metrics["margin"]["net_equity"] == pytest.approx(100.4)
    result = simulate_margin([dust], margin_used=50)
    assert result["probabilities"]["1"] == {"baseline": 0.0, "stressed": 0.0}


def test_static_fifty_percent_buffer_on_nov_22_book() -> None:
    buffer = static_maintenance_buffer(2_540.00, 3_990.00)
    assert buffer["usd"] == pytest.approx(545.00, abs=0.01)
    assert buffer["pct"] == pytest.approx((545.00 / 3990.00), abs=0.0001)


def test_daily_target_without_an_explicit_multiplier_is_two_x() -> None:
    assert infer_leverage("GraniteShares Daily Target ETF", "ETF") == 2.0
    assert infer_leverage("GraniteShares Daily Target", "EQUITY") == 1.0
    assert infer_leverage("GraniteShares Daily Target", "CRYPTOCURRENCY") == 1.0


def test_mu_title_and_macro_bar_use_look_through() -> None:
    portfolio_map = json.loads((ROOT / "portfolio_map.json").read_text())
    positions = [
        {
            "ticker": "RAM",
            "market_value": 2_400.00,
            "look_through_usd": 4_800.00,
            "leverage": 2.0,
        }
    ]
    calendar = build_calendar(
        portfolio_map,
        positions,
        datetime.fromisoformat(AS_OF),
        {"MU": 0.02},
    )
    mu = next(row for row in calendar["all"] if row["ticker"] == "MU")
    assert mu["name"] == "MU (Micron) Q1 FY27 Earnings"
    jolts = next(row for row in calendar["radar"] if row["name"].startswith("JOLTS"))
    assert jolts["exposure_usd"] == pytest.approx(4_800.00)


def test_reconstructed_curve_is_shares_times_close_plus_cash() -> None:
    first = datetime(2026, 10, 1, tzinfo=timezone.utc)
    second = datetime(2026, 10, 2, tzinfo=timezone.utc)
    curve = reconstruct_equity(
        [{"ticker": "RAM", "shares": 10}],
        5.0,
        {"RAM": [(first, 1.0), (second, 2.0)]},
    )
    assert [value for _day, value in curve] == pytest.approx([15.0, 25.0])
