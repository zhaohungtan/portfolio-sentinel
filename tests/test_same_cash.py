"""Money in is net equity minus realized and unrealized profit."""

from src.desk import same_cash_comparison


def test_same_cash_starts_together_and_ends_at_net_equity() -> None:
    levels = {
        "QQQ": [
            {"date": "2026-06-12", "close": 100.0},
            {"date": "2026-06-15", "close": 110.0},
            {"date": "2026-11-20", "close": 120.0},
        ],
        "SPY": [
            {"date": "2026-06-12", "close": 50.0},
            {"date": "2026-06-15", "close": 55.0},
            {"date": "2026-11-20", "close": 60.0},
        ],
    }
    result = same_cash_comparison(
        net_equity=2_540.00,
        realized=240.0,
        unrealized=-1_600.0,
        first_activity_date="2026-06-14",
        as_of_date="2026-11-23",
        levels=levels,
    )
    assert result is not None
    money_in = 2_540.00 - 240.0 - (-1_600.0)
    assert result["money_in"] == money_in
    assert result["portfolio"][0]["value"] == money_in
    assert result["portfolio"][-1]["date"] == "2026-11-23"
    assert result["portfolio"][-1]["value"] == 2_540.00
    assert result["benchmarks"]["QQQ"][0]["value"] == money_in
    assert result["benchmarks"]["SPY"][0]["value"] == money_in
    assert result["qqq_now"] == money_in * 1.20
    assert result["spy_now"] == money_in * 1.20
    assert result["alpha_qqq"] == (2_540.00 - money_in * 1.20) / money_in
