"""
QuantPrism — Parallel Universe Backtest Engine
Same strategy, every possible entry date → scatter distribution
"""
import json
import math
import time
import numpy as np
import pandas as pd
from datetime import datetime, timedelta

from market_data import fetch_stock_history, compute_technicals
from strategies.base import get_strategy, BacktestMetrics
from backtester import _simulate_portfolio, COST_MODELS, _resolve_strategy
from models import StrategyConfig, UserGoals


def run_parallel_backtest(config: StrategyConfig, goals: UserGoals = None,
                          start_range: str = None, end_range: str = None,
                          holding_period_days: int = 180, step_days: int = 5,
                          cost_model_name: str = "default") -> dict:
    """
    Parallel universe backtest: simulate entry on every Nth trading day.

    Returns:
        scatter_data: list of {entry_date, total_return, max_drawdown, sharpe}
        summary: {win_rate, avg_return, avg_drawdown, best_entry, worst_entry, total_entries}
        distribution: histogram bins for return distribution
    """
    t0 = time.time()

    strategy_cls, _ = _resolve_strategy(config)
    if not strategy_cls:
        return {"error": f"Strategy '{config.strategy_name}' not found"}

    import yaml
    params = yaml.safe_load(config.params_yaml) if config.params_yaml else {}
    strategy = strategy_cls(params)
    cost_model = COST_MODELS.get(cost_model_name, COST_MODELS["default"])

    if config.instrument in ("sell_put", "covered_call", "call", "put"):
        cost_model = COST_MODELS["option"]

    symbol = config.symbol_pool.split(",")[0].strip() if config.symbol_pool else "SPY"

    # Download full data ONCE
    if start_range and end_range:
        df_full = fetch_stock_history(symbol, start=start_range, end=end_range)
    else:
        df_full = fetch_stock_history(symbol, period="10y")

    if df_full.empty or len(df_full) < holding_period_days:
        return {"error": f"Insufficient data for {symbol}"}

    df_full = compute_technicals(df_full)
    risk_per_trade = goals.risk_per_trade if goals else 0.02

    # Iterate entry points
    scatter_data = []
    total_dates = len(df_full)
    max_start = total_dates - holding_period_days

    for i in range(0, max_start, step_days):
        entry_date = df_full.index[i]
        df_slice = df_full.iloc[i:i + holding_period_days].copy()

        if len(df_slice) < 20:
            continue

        signals = strategy.generate_signals(df_slice)
        for s in signals:
            s.symbol = symbol

        metrics = _simulate_portfolio(signals, df_slice,
                                      risk_per_trade=risk_per_trade,
                                      cost_model=cost_model)

        entry_str = entry_date.strftime('%Y-%m-%d') if hasattr(entry_date, 'strftime') else str(entry_date)[:10]

        scatter_data.append({
            "entry_date": entry_str,
            "total_return": round(metrics.total_return * 100, 2),
            "max_drawdown": round(metrics.max_drawdown * 100, 2),
            "sharpe": round(metrics.sharpe_ratio, 2),
            "total_trades": metrics.total_trades,
            "final_equity": round(metrics.final_equity, 2),
        })

    if not scatter_data:
        return {"error": "No valid entry points found"}

    # Summary statistics
    returns = [d["total_return"] for d in scatter_data]
    drawdowns = [d["max_drawdown"] for d in scatter_data]
    wins = [r for r in returns if r > 0]

    best_idx = np.argmax(returns)
    worst_idx = np.argmin(returns)

    summary = {
        "total_entries": len(scatter_data),
        "win_rate": round(len(wins) / len(returns) * 100, 1) if returns else 0,
        "avg_return": round(float(np.mean(returns)), 2),
        "median_return": round(float(np.median(returns)), 2),
        "avg_drawdown": round(float(np.mean(drawdowns)), 2),
        "best_entry": scatter_data[best_idx]["entry_date"],
        "best_return": scatter_data[best_idx]["total_return"],
        "worst_entry": scatter_data[worst_idx]["entry_date"],
        "worst_return": scatter_data[worst_idx]["total_return"],
        "std_return": round(float(np.std(returns)), 2),
    }

    # Distribution histogram
    hist_counts, hist_edges = np.histogram(returns, bins=20)
    distribution = [
        {"bin_start": round(float(hist_edges[i]), 1),
         "bin_end": round(float(hist_edges[i + 1]), 1),
         "count": int(hist_counts[i])}
        for i in range(len(hist_counts))
    ]

    elapsed = round(time.time() - t0, 2)

    return {
        "scatter_data": scatter_data,
        "summary": summary,
        "distribution": distribution,
        "symbol": symbol,
        "holding_period_days": holding_period_days,
        "step_days": step_days,
        "elapsed_seconds": elapsed,
    }
