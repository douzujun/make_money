"""Portfolio backtest calculation engine — pandas-based periodic rebalancing."""
import math
import logging
from datetime import date
from typing import Dict, List

import numpy as np
import pandas as pd

logger = logging.getLogger("backtest.engine")

RISK_FREE_RATE = 0.02  # 2% annual (approximate China 1-year deposit rate)


def load_prices(symbols: List[str], start_date: str, end_date: str) -> pd.DataFrame:
    """Load daily NAV prices from DB. Returns wide DataFrame indexed by date."""
    from app.core.database import SessionLocal
    from app.models.backtest import EtfPriceCache

    db = SessionLocal()
    try:
        rows = (
            db.query(EtfPriceCache)
            .filter(
                EtfPriceCache.symbol.in_(symbols),
                EtfPriceCache.date >= date.fromisoformat(start_date),
                EtfPriceCache.date <= date.fromisoformat(end_date),
            )
            .all()
        )

        data: Dict[str, Dict] = {}
        for r in rows:
            data.setdefault(r.symbol, {})[r.date] = r.nav

        df = pd.DataFrame(data)
        df.index = pd.to_datetime(df.index)
        df.sort_index(inplace=True)
        return df
    finally:
        db.close()


def _cash_nav(index: pd.DatetimeIndex) -> pd.Series:
    """Synthetic cash curve using the module's approximate risk-free rate."""
    if len(index) == 0:
        return pd.Series(dtype=float)
    days = (index - index[0]).days
    return pd.Series((1.0 + RISK_FREE_RATE) ** (days / 365.25), index=index)


def run_backtest(
    weights: Dict[str, float],
    rebalance_freq: str,
    start_date: str,
    end_date: str,
) -> dict:
    """
    Run periodic-rebalancing backtest.

    weights: {symbol: fraction}, e.g. {"510300": 0.6, "511010": 0.4}
    rebalance_freq: "1M" or "1Q"
    Returns nav_curve + metrics dict.
    """
    symbols = [s for s, w in weights.items() if w > 0 and s != "CASH"]
    cash_weight = weights.get("CASH", 0.0)
    prices = load_prices(symbols, start_date, end_date) if symbols else pd.DataFrame()

    if cash_weight > 0:
        if prices.empty:
            index = pd.date_range(start=start_date, end=end_date, freq="B")
        else:
            index = prices.index
        prices["CASH"] = _cash_nav(index)

    if prices.empty:
        return {"error": "no_data", "nav_curve": [], "metrics": {}}

    # Drop symbols with no data
    available = [s for s, w in weights.items() if w > 0 and s in prices.columns]
    if not available:
        return {"error": "no_data", "nav_curve": [], "metrics": {}}

    prices = prices[available]

    # Normalise weights to available symbols
    total_w = sum(weights[s] for s in available)
    norm_weights = {s: weights[s] / total_w for s in available}

    # Forward-fill missing trading days
    prices = prices.ffill().bfill()

    # Resample to period-end prices
    freq = "ME" if rebalance_freq == "1M" else "QE"
    period_prices = prices.resample(freq).last().dropna(how="all")

    if len(period_prices) < 2:
        return {"error": "insufficient_data", "nav_curve": [], "metrics": {}}

    # Period returns
    period_returns = period_prices.pct_change()

    # Simulate portfolio NAV with periodic rebalancing
    nav = 1.0
    nav_series = []
    current_weights = dict(norm_weights)

    for i, (dt, row) in enumerate(period_returns.iterrows()):
        if i == 0:
            nav_series.append({"date": dt.date().isoformat(), "nav": round(nav, 6)})
            continue

        period_ret = sum(
            current_weights.get(s, 0) * (float(row[s]) if not pd.isna(row[s]) else 0.0)
            for s in available
        )
        nav *= 1.0 + period_ret
        nav_series.append({"date": dt.date().isoformat(), "nav": round(nav, 6)})

        # Rebalance to target weights
        current_weights = dict(norm_weights)

    # ── Metrics ──────────────────────────────────────────────────────────────
    nav_arr = np.array([x["nav"] for x in nav_series])
    periods_per_year = 12.0 if rebalance_freq == "1M" else 4.0
    n_periods = len(nav_arr) - 1

    # Annualized return
    years = n_periods / periods_per_year
    annual_return = float((nav_arr[-1] / nav_arr[0]) ** (1.0 / years) - 1) if years > 0 else 0.0

    # Max drawdown
    peak = np.maximum.accumulate(nav_arr)
    drawdowns = (nav_arr - peak) / peak
    max_drawdown = float(drawdowns.min())

    # Sharpe ratio
    rets = np.diff(nav_arr) / nav_arr[:-1]
    excess = rets - RISK_FREE_RATE / periods_per_year
    sharpe = (
        float(np.mean(excess) / np.std(excess) * math.sqrt(periods_per_year))
        if np.std(excess) > 1e-10
        else 0.0
    )

    return {
        "nav_curve": nav_series,
        "metrics": {
            "annual_return": round(annual_return, 4),
            "max_drawdown": round(max_drawdown, 4),
            "sharpe_ratio": round(sharpe, 4),
        },
    }


def get_ma200_events(
    symbol: str = "510300",
    start_date: str = "2013-01-01",
    end_date: str = "2026-12-31",
) -> List[dict]:
    """Return dates where symbol crosses its 200-day MA (up or down)."""
    prices = load_prices([symbol], start_date, end_date)
    if prices.empty or symbol not in prices.columns:
        return []

    s = prices[symbol].dropna()
    if len(s) < 200:
        return []

    ma200 = s.rolling(200, min_periods=200).mean()
    above = (s > ma200).dropna()
    crossings = above.astype(int).diff().dropna()

    events = []
    for dt, val in crossings.items():
        if val == 1:
            events.append({
                "date": dt.date().isoformat(),
                "type": "cross_up",
                "label": "沪深300 回升至 MA200 上方",
            })
        elif val == -1:
            events.append({
                "date": dt.date().isoformat(),
                "type": "cross_down",
                "label": "沪深300 跌破 MA200",
            })

    return events


def get_bear_periods(
    symbol: str = "510300",
    start_date: str = "2013-01-01",
    end_date: str = "2026-12-31",
) -> List[dict]:
    """
    Return date ranges when symbol was below its 200-day MA.
    Each item: {"start": "YYYY-MM-DD", "end": "YYYY-MM-DD"}
    Used by the frontend to draw red background shading on the NAV chart.
    """
    prices = load_prices([symbol], start_date, end_date)
    if prices.empty or symbol not in prices.columns:
        return []

    s = prices[symbol].dropna()
    if len(s) < 200:
        return []

    ma200 = s.rolling(200, min_periods=200).mean()
    below = (s < ma200).dropna()

    periods = []
    in_bear = False
    bear_start = None

    for dt, is_below in below.items():
        if is_below and not in_bear:
            in_bear = True
            bear_start = dt
        elif not is_below and in_bear:
            in_bear = False
            periods.append({
                "start": bear_start.date().isoformat(),
                "end": dt.date().isoformat(),
            })

    if in_bear and bear_start is not None:
        periods.append({
            "start": bear_start.date().isoformat(),
            "end": end_date,
        })

    return periods
