"""Verify that the credential-free demo reconciles across dashboard sections."""

from pathlib import Path
import shutil

import pytest

from src.desk import compose_dashboard


def test_synthetic_dashboard_reconciles_without_a_broker_snapshot(tmp_path):
    root = Path(__file__).resolve().parents[1]
    shutil.copytree(root / "data" / "fixtures", tmp_path / "data" / "fixtures")
    shutil.copyfile(root / "portfolio_map.json", tmp_path / "portfolio_map.json")

    data = compose_dashboard(tmp_path)
    capital = data["capital"]
    comparison = data["performance"]["same_cash"]

    assert data["source"] == "fixture"
    assert data["broker_net_equity"] is None
    assert len(data["heatmap"]) == 5
    assert sum(tile["market_value"] for tile in data["heatmap"]) == pytest.approx(3990)
    assert comparison["portfolio"][-1]["value"] == capital["net_equity"]
    assert capital["gross_holdings"] + capital["margin_debt"] == pytest.approx(capital["net_equity"])
    assert {symbol for symbol, points in comparison["benchmarks"].items() if points} == {"QQQ", "SPY"}
    assert all("account_mask" not in account for account in data["accounts"])
