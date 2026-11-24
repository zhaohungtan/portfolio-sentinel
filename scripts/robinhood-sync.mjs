// Codex owns OAuth and calls the fixed set of read-only Robinhood tools below.
import { spawn } from "node:child_process";
import { createInterface } from "node:readline";

const server = "robinhood-trading";
const allowed = [
  "get_accounts", "get_portfolio", "get_equity_positions", "get_equity_quotes",
  "get_option_positions", "get_crypto_positions", "get_crypto_quotes", "get_realized_pnl",
];
const child = spawn("codex", [
  "app-server", "--listen", "stdio://",
  "-c", `mcp_servers.${server}.enabled_tools=${JSON.stringify(allowed)}`,
], { stdio: ["pipe", "pipe", "ignore"] });
const lines = createInterface({ input: child.stdout });
const pending = new Map();
let sequence = 0;

function disconnect() {
  for (const request of pending.values()) request.reject(new Error("Codex disconnected"));
  pending.clear();
}
child.on("error", disconnect);
child.on("close", disconnect);
child.stdin.on("error", disconnect);
lines.on("line", (line) => {
  let message;
  try { message = JSON.parse(line); } catch { return; }
  const request = pending.get(message.id);
  if (!request) return;
  pending.delete(message.id);
  if (message.error) request.reject(new Error(`${request.method} failed`));
  else request.resolve(message.result);
});

function rpc(method, params) {
  const id = ++sequence;
  return new Promise((resolve, reject) => {
    pending.set(id, { method, resolve, reject });
    child.stdin.write(JSON.stringify({ id, method, params }) + "\n");
  });
}

const timer = setTimeout(() => {
  disconnect();
  child.kill();
}, 35_000);

function number(value) {
  if (value == null || value === "" || !Number.isFinite(Number(value))) {
    throw new Error("Invalid broker numeric field");
  }
  return Number(value);
}

function price(quote) {
  const regular = Date.parse(quote.venue_last_trade_time);
  const extended = Date.parse(quote.venue_last_non_reg_trade_time);
  const marks = [
    [quote.last_trade_price, regular],
    [quote.last_non_reg_trade_price, extended],
  ].filter(([value]) => Number(value) > 0);
  marks.sort((a, b) => (Number.isFinite(b[1]) ? b[1] : 0) - (Number.isFinite(a[1]) ? a[1] : 0));
  if (!marks.length) throw new Error("Missing equity quote");
  const [value, stamp] = marks[0];
  return { current_price: number(value), quote_as_of: Number.isFinite(stamp) ? new Date(stamp).toISOString() : null };
}

async function sync() {
  await rpc("initialize", { clientInfo: { name: "sentinel", version: "1.0.0" } });
  child.stdin.write('{"method":"initialized"}\n');
  const { thread } = await rpc("thread/start", {
    ephemeral: true, approvalPolicy: "never", sandbox: "read-only",
  });
  async function read(tool, args = {}) {
    if (!allowed.includes(tool)) throw new Error("Tool is outside the read allowlist");
    const result = await rpc("mcpServer/tool/call", {
      server, tool, threadId: thread.id, arguments: args,
    });
    const payload = result.structuredContent ?? JSON.parse(result.content[0]?.text ?? "{}");
    if (result.isError || !payload.data) throw new Error(`${tool} returned no data`);
    return payload.data;
  }
  async function pages(tool, args, key) {
    const rows = [];
    const seen = new Set();
    let cursor;
    do {
      const data = await read(tool, cursor ? { ...args, cursor } : args);
      if (!Array.isArray(data[key])) throw new Error(`${tool} returned an invalid page`);
      rows.push(...data[key]);
      cursor = data.next;
      if (cursor && seen.has(cursor)) throw new Error(`${tool} repeated a cursor`);
      seen.add(cursor);
    } while (cursor);
    return rows;
  }

  const last4 = process.env.ROBINHOOD_ACCOUNT_LAST4;
  if (!/^\d{4}$/.test(last4 ?? "")) throw new Error("Set ROBINHOOD_ACCOUNT_LAST4 to the four-digit account suffix");
  const { accounts } = await read("get_accounts");
  const matches = accounts.filter(({ rhs_account_number }) => String(rhs_account_number).endsWith(last4));
  if (matches.length !== 1 || matches[0].deactivated || matches[0].permanently_deactivated) throw new Error("Could not identify the configured active account");
  const primary = matches[0];
  const rhs = String(primary.rhs_account_number);
  const [equity, options, crypto, pnl] = await Promise.all([
    pages("get_equity_positions", { account_number: rhs, nonzero: true }, "positions"),
    pages("get_option_positions", { account_number: rhs, nonzero: true }, "positions"),
    primary.rhc_account_number ? pages("get_crypto_positions", { rhs_account_number: rhs }, "results") : [],
    read("get_realized_pnl", { account_number: rhs, span: "all" }),
  ]);
  const equities = equity.filter((row) => number(row.quantity) !== 0);
  const coins = crypto.filter((row) => number(row.quantity) !== 0);
  const symbols = [...new Set(equities.map((row) => row.symbol))];
  const [market, coinMarket, portfolio] = await Promise.all([
    symbols.length ? read("get_equity_quotes", { symbols }) : { results: [] },
    coins.length ? read("get_crypto_quotes", {
      symbols: [...new Set(coins.map((row) => `${row.currency.code}-USD`))], rhs_account_number: rhs,
    }) : { results: [] },
    read("get_portfolio", { account_number: rhs }),
  ]);
  const equitiesBySymbol = new Map(market.results.filter((row) => row.quote).map(({ quote }) => [quote.symbol, quote]));
  const coinsBySymbol = new Map(coinMarket.results.map((quote) => [quote.symbol.replace("-", ""), quote]));
  const positions = equities.map((row) => {
    const shares = number(row.quantity);
    const mark = price(equitiesBySymbol.get(row.symbol) ?? {});
    return {
      ticker: row.symbol, asset_class: "equity", shares,
      avg_cost: number(row.average_buy_price), ...mark,
      market_value: shares * mark.current_price,
    };
  });
  for (const row of coins) {
    const ticker = row.currency.code;
    const quote = coinsBySymbol.get(`${ticker}USD`);
    const current_price = number(quote?.mark_price);
    const shares = number(row.quantity);
    positions.push({
      ticker, asset_class: "crypto", shares, avg_cost: null, current_price,
      market_value: shares * current_price, quote_as_of: quote.updated_at ?? null,
    });
  }
  return {
    source: "robinhood-mcp",
    as_of: new Date().toISOString(),
    accounts: [{
      label: "Individual Investing", account_mask: last4, role: "primary",
      account_type: "individual", is_default: primary.is_default, is_agentic: false,
      cash: number(portfolio.cash), total_value: number(portfolio.total_value),
      pending_deposits: number(portfolio.pending_deposits),
      buying_power: number(portfolio.buying_power.buying_power),
      unleveraged_buying_power: number(portfolio.buying_power.unleveraged_buying_power),
      crypto_buying_power: portfolio.crypto_buying_power?.buying_power == null
        ? null : number(portfolio.crypto_buying_power.buying_power),
      realized_pnl_all: number(pnl.total_returns),
      unsupported_positions: options.length,
      positions,
    }],
  };
}
try {
  console.log(JSON.stringify(await sync()));
} catch (error) {
  console.error(error.message);
  process.exitCode = 1;
} finally {
  clearTimeout(timer);
  lines.close();
  child.kill();
}
