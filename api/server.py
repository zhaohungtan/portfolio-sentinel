"""Read-only FastAPI bridge. Robinhood refresh uses the local Codex MCP bridge."""

from __future__ import annotations

from threading import Lock
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from src.desk import compose_dashboard, filter_news, refresh_broker_dashboard, refresh_offline, sync_news

_broker_lock = Lock()
_local_origins = {"http://localhost:3000", "http://127.0.0.1:3000"}

app = FastAPI(title="Sentinel desk", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=sorted(_local_origins),
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


@app.get("/api/dashboard")
def dashboard(response: Response, refresh_quotes: bool = False) -> dict[str, Any]:
    response.headers["Cache-Control"] = "no-store"
    return compose_dashboard(refresh_quotes=refresh_quotes)


@app.get("/api/performance")
def performance() -> dict[str, Any]:
    return compose_dashboard()["performance"]


@app.get("/api/news")
def news(
    window: str = Query(default="7d"),
    scope: str = Query(default="all"),
    polarity: str = Query(default="all"),
) -> dict[str, Any]:
    tape = compose_dashboard()["news"]
    return {"items": filter_news(tape, window=window, scope=scope, polarity=polarity)}


@app.post("/api/refresh-offline")
def refresh() -> dict[str, Any]:
    return refresh_offline()


@app.post("/api/sync-news")
def news_sync() -> dict[str, Any]:
    return sync_news()


@app.post("/api/sync-robinhood")
def robinhood_sync(request: Request, response: Response) -> dict[str, Any]:
    origin = request.headers.get("origin")
    if origin is not None and origin not in _local_origins:
        raise HTTPException(status_code=403, detail="Robinhood sync is limited to the local dashboard.")
    response.headers["Cache-Control"] = "no-store"
    if not _broker_lock.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="Robinhood sync is already running.")
    try:
        return refresh_broker_dashboard()
    except Exception as exc:
        raise HTTPException(
            status_code=503, detail="Robinhood sync could not complete. Check the Codex MCP connection."
        ) from exc
    finally:
        _broker_lock.release()
