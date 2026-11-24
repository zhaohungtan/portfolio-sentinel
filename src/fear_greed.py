"""CNN Fear & Greed index. A failed fetch leaves the last saved file, or nothing."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen

URL = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Referer": "https://edition.cnn.com/markets/fear-and-greed",
    "Accept": "application/json, text/plain, */*",
}


def band(score: float) -> str:
    if score < 25:
        return "extreme fear"
    if score < 45:
        return "fear"
    if score < 55:
        return "neutral"
    if score < 75:
        return "greed"
    return "extreme greed"


def parse_fear_greed(payload: dict[str, Any]) -> dict[str, Any] | None:
    current = payload.get("fear_and_greed") or {}
    if current.get("score") is None:
        return None
    score = _clamp(float(current["score"]))
    rating = str(current.get("rating") or band(score)).strip().lower()
    points: dict[str, dict[str, Any]] = {}
    history = (payload.get("fear_and_greed_historical") or {}).get("data") or []
    for entry in history:
        if entry.get("y") is None or entry.get("x") is None:
            continue
        value = _clamp(float(entry["y"]))
        day = datetime.fromtimestamp(float(entry["x"]) / 1000.0, tz=timezone.utc).date().isoformat()
        points[day] = {
            "date": day,
            "score": value,
            "rating": str(entry.get("rating") or band(value)).strip().lower(),
        }
    series = [points[day] for day in sorted(points)]
    return {"score": score, "rating": rating, "series": series}


def load_fear_greed(repo: Path, start_date: str | None = None) -> dict[str, Any] | None:
    fresh = _fetch()
    parsed = parse_fear_greed(fresh) if fresh else None
    path = repo / "data" / "fear_greed.json"
    if parsed is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(parsed) + "\n", encoding="utf-8")
    elif path.exists():
        cached = json.loads(path.read_text(encoding="utf-8"))
        parsed = cached if isinstance(cached, dict) else None
    if not parsed:
        return None
    series = list(parsed.get("series") or [])
    if start_date:
        series = [row for row in series if str(row.get("date")) >= start_date]
    return {
        "score": parsed.get("score"),
        "rating": parsed.get("rating"),
        "series": series,
    }


def _fetch() -> dict[str, Any] | None:
    request = Request(URL, headers=_HEADERS)
    try:
        with urlopen(request, timeout=12) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (URLError, TimeoutError, json.JSONDecodeError, OSError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def _clamp(score: float) -> float:
    return max(0.0, min(100.0, score))
