# Portfolio Sentinel

Portfolio Sentinel is a read-only investment dashboard I built to answer three questions: what is the account worth, where is risk concentrated, and how does its value compare with investing the same starting capital in QQQ or SPY?

The project combines authenticated broker data, market history, and news into a dashboard with a holdings heat map, margin scenarios, and a catalyst calendar. The included demo uses fictional balances, positions, and benchmark prices. It runs without brokerage credentials.

## How the data moves

| Stage | Implementation |
| --- | --- |
| Ingest | A local Node.js bridge uses Codex-managed OAuth to page through Robinhood account and position data and select the freshest available quote. Yahoo Finance supplies daily adjusted prices for the live benchmarks. |
| Normalize | Python converts source records into a common positions snapshot, retains source timestamps, and atomically saves verified broker reads. Broker-reported net equity is carried through to the dashboard. |
| Store | The audit pipeline uses DuckDB and SQL to store position snapshots, high-water marks, and deduplicated news catalysts. |
| Analyze | Python and NumPy calculate concentration, leveraged look-through exposures, and simulated maintenance-threshold breaches under baseline and stress assumptions. |
| Present | FastAPI serves the analytics to a TypeScript and Next.js dashboard with a holdings heat map, benchmark chart, and read-only scenario controls. |

## Two decisions worth inspecting

- **Keep broker values distinct from market estimates.** Refreshing market quotes can update a valuation estimate while the broker snapshot remains intact. The benchmark chart uses the broker's reported net equity for its portfolio endpoint. The live QQQ and SPY paths assume a single investment of estimated starting capital because the brokerage deposit and withdrawal ledger is unavailable through the current connection.
- **Constrain and verify the agent integration.** The bridge calls an explicit list of read tools through Codex. The dataset, authorization, and account configuration stay local. Tests check stale-quote rejection, holding changes after a broker refresh, benchmark arithmetic, and deterministic margin scenarios.

The maintenance thresholds and simulated prices are model assumptions. The simulation is useful for comparing scenarios and does not reproduce the broker's margin model.

## Run locally

Requires Python 3.11+ and Node.js 20.9+.

```sh
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
npm --prefix web ci
./dev.sh
```

Open [the local dashboard](http://localhost:3000). The demo includes five synthetic equity positions and both benchmark lines. Financial amounts and share counts start hidden. Use the visibility toggle to reveal them.

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
