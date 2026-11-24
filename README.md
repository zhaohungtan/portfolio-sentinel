# Portfolio Sentinel

Portfolio Sentinel is a local, read-only dashboard for portfolio risk, positions, market catalysts, and a QQQ and S&P 500 comparison. The repository ships with a fictional portfolio and fictional benchmark prices for the demo. The live benchmark uses Yahoo Finance daily prices and estimates starting capital when a contribution ledger is unavailable.

## Run locally

Requires Python 3.11+ and Node.js 20.9+.

```sh
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
npm --prefix web ci
./dev.sh
```

Open [the local dashboard](http://localhost:3000). Financial amounts and share counts start hidden. Use the visibility toggle to reveal them.

## Optional Robinhood sync

Authorize the official [Robinhood Trading MCP](https://robinhood.com/us/en/support/articles/onboarding-an-external-agent/) in a recent Codex CLI with app-server support.

```sh
codex mcp add robinhood-trading --url https://agent.robinhood.com/mcp/trading
```

Set `ROBINHOOD_ACCOUNT_LAST4` to your selected brokerage account's four-digit suffix in your local shell before running `./dev.sh`. Then click **Sync Robinhood**. The bridge uses an explicit allowlist of read tools. OAuth stays in Codex. Live snapshots and caches are stored locally and ignored by Git.

Keep the dashboard bound to loopback. Its visibility toggle masks values on screen. Local API responses contain portfolio values.

## Checks

```sh
.venv/bin/pytest -q
.venv/bin/sentinel smoke
```
