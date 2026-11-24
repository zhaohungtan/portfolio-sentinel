"""Fear and greed scores stay on 0–100, and a missed fetch stays empty."""

from datetime import datetime, timezone

from src.fear_greed import band, load_fear_greed, parse_fear_greed


def _ms(iso: str) -> int:
    return int(datetime.fromisoformat(iso).replace(tzinfo=timezone.utc).timestamp() * 1000)


def test_scores_stay_on_the_scale_and_ratings_map_to_five_bands() -> None:
    assert band(0) == "extreme fear"
    assert band(24.9) == "extreme fear"
    assert band(25) == "fear"
    assert band(44.9) == "fear"
    assert band(45) == "neutral"
    assert band(54.9) == "neutral"
    assert band(55) == "greed"
    assert band(74.9) == "greed"
    assert band(75) == "extreme greed"
    assert band(100) == "extreme greed"
    parsed = parse_fear_greed(
        {
            "fear_and_greed": {"score": 120, "rating": "Extreme Greed"},
            "fear_and_greed_historical": {
                "data": [
                    {"x": _ms("2026-06-12"), "y": -4, "rating": "extreme fear"},
                    {"x": _ms("2026-06-15"), "y": 48, "rating": "neutral"},
                ]
            },
        }
    )
    assert parsed is not None
    assert parsed["score"] == 100
    assert parsed["rating"] == "extreme greed"
    assert parsed["series"][0]["score"] == 0
    assert parsed["series"][1]["rating"] == "neutral"


def test_missing_response_leaves_the_field_empty(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("src.fear_greed._fetch", lambda: None)
    assert load_fear_greed(tmp_path, start_date="2026-06-14") is None


def test_series_starts_on_the_first_trade_date(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        "src.fear_greed._fetch",
        lambda: {
            "fear_and_greed": {"score": 32, "rating": "fear"},
            "fear_and_greed_historical": {
                "data": [
                    {"x": _ms("2026-06-01"), "y": 60, "rating": "greed"},
                    {"x": _ms("2026-06-14"), "y": 32, "rating": "fear"},
                ]
            },
        },
    )
    loaded = load_fear_greed(tmp_path, start_date="2026-06-14")
    assert loaded is not None
    assert [row["date"] for row in loaded["series"]] == ["2026-06-14"]
