"""
QuantPrism — Multi-Strategy Comparison Engine
Compare multiple strategies on the same underlying over the same period
"""
import json
import yaml
import numpy as np
import pandas as pd
from datetime import datetime

from market_data import fetch_stock_history, compute_technicals
from strategies.base import get_strategy, BacktestMetrics
from backtester import _simulate_portfolio, COST_MODELS
from models import StrategyConfig, UserGoals

STRATEGY_COLORS = ['#3b82f6', '#22c55e', '#eab308', '#8b5cf6', '#ef4444', '#06b6d4']


def compare_strategies(configs: list, symbol: str = "SPY",
                       start_date: str = None, end_date: str = None,
                       goals: UserGoals = None) -> dict:
    """
    Run multiple strategies on the same data and return comparative results.

    Returns:
        strategies: list of {name, color, metrics, equity_curve_json}
        comparison_table: dict of metric_name → [{strategy, value}]
    """
    # Download data once
    if start_date and end_date:
        df = fetch_stock_history(symbol, start=start_date, end=end_date)
    else:
        df = fetch_stock_history(symbol, period="5y")

    if df.empty:
        return {"error": f"No data for {symbol}"}

    df = compute_technicals(df)
    risk_per_trade = goals.risk_per_trade if goals else 0.02

    results = []
    for i, config in enumerate(configs):
        strategy_cls = get_strategy(config.strategy_name)
        if not strategy_cls:
            continue

        params = yaml.safe_load(config.params_yaml) if config.params_yaml else {}
        strategy = strategy_cls(params)

        cost_model = COST_MODELS["default"]
        if config.instrument in ("sell_put", "covered_call"):
            cost_model = COST_MODELS["option"]

        signals = strategy.generate_signals(df.copy())
        for s in signals:
            s.symbol = symbol

        metrics = _simulate_portfolio(signals, df, risk_per_trade=risk_per_trade,
                                      cost_model=cost_model, collect_daily=True)

        color = STRATEGY_COLORS[i % len(STRATEGY_COLORS)]
        display_name = config.display_name or config.strategy_name

        # Build equity curve for chart overlay
        equity_data = []
        if metrics.daily_details:
            for d in metrics.daily_details:
                equity_data.append([d["date"], d["equity"]])

        results.append({
            "name": display_name,
            "color": color,
            "config_id": config.id,
            "total_return": round(metrics.total_return * 100, 2),
            "annual_return": round(metrics.annual_return * 100, 2),
            "max_drawdown": round(metrics.max_drawdown * 100, 2),
            "sharpe": round(metrics.sharpe_ratio, 2),
            "sortino": round(metrics.sortino_ratio, 2),
            "win_rate": round(metrics.win_rate * 100, 1),
            "total_trades": metrics.total_trades,
            "profit_factor": round(metrics.profit_factor, 2),
            "equity_curve": equity_data,
            "sparkline": equity_data[-60:] if len(equity_data) > 60 else equity_data,
        })

    if not results:
        return {"error": "No valid strategies to compare"}

    # Build comparison table (find best/worst for highlighting)
    metrics_keys = ["total_return", "annual_return", "max_drawdown", "sharpe",
                    "sortino", "win_rate", "total_trades", "profit_factor"]
    comparison = {}
    for key in metrics_keys:
        values = [{"name": r["name"], "value": r[key], "color": r["color"]} for r in results]
        # Best: highest for all except max_drawdown (least negative = best)
        if key == "max_drawdown":
            best_val = max(v["value"] for v in values)
            worst_val = min(v["value"] for v in values)
        else:
            best_val = max(v["value"] for v in values)
            worst_val = min(v["value"] for v in values)
        for v in values:
            v["is_best"] = v["value"] == best_val and len(values) > 1
            v["is_worst"] = v["value"] == worst_val and len(values) > 1
        comparison[key] = values

    return {
        "strategies": results,
        "comparison": comparison,
        "symbol": symbol,
        "period": f"{start_date or 'auto'} ~ {end_date or 'now'}",
    }
