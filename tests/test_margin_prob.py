"""Closed-form buffers and a zero-volatility Monte Carlo."""

from __future__ import annotations

import pytest

from src.margin_prob import simulate_margin, uniform_drops


def test_uniform_drop_matches_both_maintenance_rules() -> None:
    drops = uniform_drops(10_000.0, 6_000.0, 2_000.0)
    assert drops["baseline_drop_pct"] == pytest.approx(1.0 - 2_000.0 / (0.75 * 10_000.0))
    assert drops["baseline_drop_usd"] == pytest.approx(10_000.0 - 2_000.0 / 0.75)
    cushion = 0.50 * 6_000.0 + 0.75 * 4_000.0
    assert drops["stressed_drop_pct"] == pytest.approx(1.0 - 2_000.0 / cushion)
    assert drops["already_in_baseline_call"] is False


def test_zero_volatility_has_no_margin_call() -> None:
    positions = [
        {
            "ticker": "RAM",
            "market_value": 6_000.0,
            "leverage": 2.0,
            "sector_cluster": "AI_Infrastructure",
            "sigma": 0.0,
        },
        {
            "ticker": "MP",
            "market_value": 4_000.0,
            "leverage": 1.0,
            "sector_cluster": "Critical_Minerals",
            "sigma": 0.0,
        },
    ]
    result = simulate_margin(positions, 2_000.0, n_paths=300, seed=7)
    assert result["probabilities"]["1"]["baseline"] == 0.0
    assert result["probabilities"]["5"]["stressed"] == 0.0
    assert result["probabilities"]["21"]["baseline"] == 0.0
    assert result["pnl_percentiles_21d"][2]["pnl_usd"] == pytest.approx(0.0)


def test_no_margin_debit_cannot_be_called() -> None:
    result = simulate_margin(
        [{"ticker": "NVDA", "market_value": 100.0, "leverage": 1.0, "sigma": 0.04}],
        0.0,
        n_paths=50,
    )
    assert result["probabilities"]["1"]["baseline"] == 0.0
    assert result["drops"]["baseline_drop_usd"] is None
