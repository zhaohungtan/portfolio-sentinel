"""Refresh the local book through the authenticated Codex MCP bridge."""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any


def write_json_atomic(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as file:
        temporary = Path(file.name)
        try:
            json.dump(payload, file, allow_nan=False, indent=2)
            file.write("\n")
            file.flush()
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)


def sync_broker_book(repo: Path) -> dict[str, Any]:
    last4 = os.environ.get("ROBINHOOD_ACCOUNT_LAST4", "")
    if not re.fullmatch(r"[0-9]{4}", last4):
        raise RuntimeError("Set ROBINHOOD_ACCOUNT_LAST4 before enabling live sync.")
    result = subprocess.run(
        ["node", str(repo / "scripts" / "robinhood-sync.mjs")],
        cwd=repo, capture_output=True, text=True, timeout=40, check=False,
    )
    if result.returncode:
        raise RuntimeError("Robinhood sync failed. Check the Codex Robinhood connection.")
    book = json.loads(result.stdout)
    account = book["accounts"][0]
    if book.get("source") != "robinhood-mcp" or account.get("account_mask") != last4:
        raise RuntimeError("Robinhood returned an unexpected account.")
    path = repo / "data" / "live_book.json"
    if path.exists():
        previous = json.loads(path.read_text(encoding="utf-8"))
        for saved in previous.get("accounts", []):
            if str(saved.get("account_mask")) == last4 and saved.get("first_activity_date"):
                account["first_activity_date"] = saved["first_activity_date"]
                break
    write_json_atomic(path, book)
    return book
