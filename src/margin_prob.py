"""Fat-tail margin-call probabilities for the live equity book.

Paths use a multivariate Student-t (df=5) so one bad day is heavier than a
normal model. Maintenance is reapplied to the shocked market value.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

import numpy as np

from src.constants import AI_CLUSTER, MAINTENANCE_RATE

STUDENT_DF = 5.0
AI_CORRELATION = 0.65
OTHER_CORRELATION = 0.30
DEFAULT_PATHS = 10_000
DEFAULT_SEED = 7
HORIZONS = (1, 5, 21)
PERCENTILES = (5, 25, 50, 75, 95)
STRESSED_LEVERED_RATE = 0.50


def uniform_drops(
    equity_value: float, levered_value: float, margin_used: float
) -> dict[str, float | None]:
    """Closed-form uniform shock that reaches each maintenance threshold.

    Baseline maintenance is 25% of the whole equity book. The stressed rule
    uses 50% on 2x ETF value and 25% on everything else. A non-positive
    margin debit cannot be called.
    """
    equity = float(equity_value)
    levered = min(float(levered_value), equity)
    other = max(equity - levered, 0.0)
    margin = float(margin_used)
    if equity <= 0 or margin <= 0:
        return {
            "baseline_drop_usd": None,
            "baseline_drop_pct": None,
            "stressed_drop_usd": None,
            "stressed_drop_pct": None,
            "already_in_baseline_call": False,
            "already_in_stressed_call": False,
        }
    baseline_floor = margin / (1.0 - MAINTENANCE_RATE)
    stressed_cushion = STRESSED_LEVERED_RATE * levered + (1.0 - MAINTENANCE_RATE) * other
    return {
        "baseline_drop_usd": _drop_dollars(equity, baseline_floor),
        "baseline_drop_pct": _drop_fraction(equity, baseline_floor),
        "stressed_drop_usd": _drop_dollars(equity, equity - _room(equity, stressed_cushion, margin)),
        "stressed_drop_pct": _stressed_fraction(equity, stressed_cushion, margin),
        "already_in_baseline_call": equity <= baseline_floor,
        "already_in_stressed_call": (equity - margin) <= (
            STRESSED_LEVERED_RATE * levered + MAINTENANCE_RATE * other
        ),
    }


def static_maintenance_buffer(net_equity: float, gross_holdings: float) -> dict[str, float]:
    """Net equity minus 50% of gross holdings.

    A book with no holdings reports zeros.
    """
    gross = float(gross_holdings)
    if gross <= 0:
        return {"usd": 0.0, "pct": 0.0}
    usd = float(net_equity) - STRESSED_LEVERED_RATE * gross
    return {"usd": usd, "pct": usd / gross}


def simulate_margin(
    positions: Sequence[Mapping[str, Any]],
    margin_used: float,
    *,
    n_paths: int = DEFAULT_PATHS,
    seed: int = DEFAULT_SEED,
    horizons: Sequence[int] = HORIZONS,
) -> dict[str, Any]:
    """Probability of touching a margin call within each horizon."""
    from src.quant_engine import is_active_position

    rows = [dict(row) for row in positions if is_active_position(row)]
    equity = float(sum(float(row["market_value"]) for row in rows))
    levered_now = float(
        sum(float(row["market_value"]) for row in rows if float(row.get("leverage") or 1.0) > 1.0)
    )
    drops = uniform_drops(equity, levered_now, margin_used)
    horizon_list = tuple(int(day) for day in horizons)
    empty = {
        "equity_value": equity,
        "levered_value": levered_now,
        "margin_used": float(margin_used),
        "paths": int(n_paths),
        "seed": int(seed),
        "degrees_of_freedom": STUDENT_DF,
        "drops": drops,
        "probabilities": {
            str(day): {"baseline": 0.0, "stressed": 0.0} for day in horizon_list
        },
        "pnl_percentiles_21d": [],
    }
    if not rows or equity <= 0 or float(margin_used) <= 0 or n_paths <= 0:
        return empty

    market = np.array([float(row["market_value"]) for row in rows], dtype=float)
    leverage = np.array([float(row.get("leverage") or 1.0) for row in rows], dtype=float)
    sigma = np.array([max(float(row.get("sigma") or 0.0), 0.0) for row in rows], dtype=float)
    is_levered = leverage > 1.0
    clusters = [str(row.get("sector_cluster") or "") for row in rows]
    longest = max(horizon_list)
    shocked = _paths(market, leverage, sigma, clusters, n_paths, longest, seed)
    # shocked: (paths, days, names) market value at each close
    probabilities: dict[str, dict[str, float]] = {}
    for day in horizon_list:
        window = shocked[:, :day, :]
        total = window.sum(axis=2)
        levered = window[:, :, is_levered].sum(axis=2) if is_levered.any() else np.zeros_like(total)
        other = total - levered
        baseline_hit = np.any(total < (float(margin_used) / (1.0 - MAINTENANCE_RATE)), axis=1)
        net = total - float(margin_used)
        required = STRESSED_LEVERED_RATE * levered + MAINTENANCE_RATE * other
        stressed_hit = np.any(net < required, axis=1)
        probabilities[str(day)] = {
            "baseline": float(baseline_hit.mean()),
            "stressed": float(stressed_hit.mean()),
        }
    terminal = shocked[:, -1, :].sum(axis=1) - equity
    pct_values = np.percentile(terminal, PERCENTILES)
    empty["probabilities"] = probabilities
    empty["pnl_percentiles_21d"] = [
        {"percentile": int(level), "pnl_usd": float(value)}
        for level, value in zip(PERCENTILES, pct_values, strict=True)
    ]
    return empty


def positions_from_book(
    book: Mapping[str, Any],
    portfolio_map: Mapping[str, Any],
    sigmas: Mapping[str, float | None],
) -> list[dict[str, Any]]:
    """Equity rows the simulator needs. Dust and options are left out."""
    from src.quant_engine import select_primary_account, underlying_candidates

    from src.quant_engine import is_active_position

    account = select_primary_account(book)
    rows: list[dict[str, Any]] = []
    for position in account.get("positions") or []:
        if str(position.get("asset_class") or "equity") != "equity":
            continue
        if not is_active_position(position):
            continue
        market_value = float(position.get("market_value") or 0.0)
        ticker = str(position["ticker"])
        meta = dict(portfolio_map.get(ticker) or {})
        leverage = float(meta.get("leverage") or 1.0)
        sigma = _first_sigma(underlying_candidates(ticker, meta), sigmas)
        rows.append(
            {
                "ticker": ticker,
                "market_value": market_value,
                "leverage": leverage,
                "sector_cluster": meta.get("sector_cluster"),
                "sigma": 0.0 if sigma is None else float(sigma),
            }
        )
    return rows


def _paths(
    market: np.ndarray,
    leverage: np.ndarray,
    sigma: np.ndarray,
    clusters: list[str],
    n_paths: int,
    n_days: int,
    seed: int,
) -> np.ndarray:
    names = len(market)
    if names == 0 or n_paths <= 0 or n_days <= 0:
        return np.zeros((max(n_paths, 0), max(n_days, 0), 0))
    corr = _correlation(clusters)
    chol = np.linalg.cholesky(corr)
    rng = np.random.default_rng(seed)
    gaussian = rng.standard_normal((n_paths, n_days, names))
    mixed = gaussian @ chol.T
    chi = rng.chisquare(STUDENT_DF, size=(n_paths, n_days, 1))
    draw = mixed / np.sqrt(chi / STUDENT_DF)
    variance_scale = np.sqrt(STUDENT_DF / (STUDENT_DF - 2.0))
    underlying = draw / variance_scale * sigma.reshape(1, 1, names)
    position_return = underlying * leverage.reshape(1, 1, names)
    gross = np.maximum(1.0 + position_return, 0.0)
    values = np.empty_like(gross)
    running = np.broadcast_to(market, (n_paths, names)).copy()
    for day in range(n_days):
        running *= gross[:, day, :]
        values[:, day, :] = running
    return values


def _correlation(clusters: list[str]) -> np.ndarray:
    count = len(clusters)
    corr = np.full((count, count), OTHER_CORRELATION, dtype=float)
    np.fill_diagonal(corr, 1.0)
    for i, left in enumerate(clusters):
        if left != AI_CLUSTER:
            continue
        for j in range(i + 1, count):
            if clusters[j] == AI_CLUSTER:
                corr[i, j] = AI_CORRELATION
                corr[j, i] = AI_CORRELATION
    return corr


def _first_sigma(
    candidates: Sequence[str], sigmas: Mapping[str, float | None]
) -> float | None:
    for symbol in candidates:
        value = sigmas.get(symbol)
        if value is not None:
            return float(value)
    return None


def _drop_dollars(equity: float, floor: float) -> float:
    if equity <= floor:
        return 0.0
    return equity - floor


def _drop_fraction(equity: float, floor: float) -> float:
    if equity <= floor:
        return 0.0
    return (equity - floor) / equity


def _room(equity: float, cushion_rate_dollars: float, margin: float) -> float:
    """How far equity can fall, in dollars, before the stressed rule binds.

    cushion_rate_dollars is (0.50*L + 0.75*U) at today's weights. Under a
    uniform shock both sides shrink together, so the surviving equity must
    stay above margin / that cushion fraction of today's equity.
    """
    if cushion_rate_dollars <= 0:
        return equity
    surviving = margin * equity / cushion_rate_dollars
    return max(equity - surviving, 0.0)


def _stressed_fraction(equity: float, cushion: float, margin: float) -> float:
    if cushion <= 0:
        return 0.0
    surviving = margin * equity / cushion
    if equity <= surviving:
        return 0.0
    return (equity - surviving) / equity
