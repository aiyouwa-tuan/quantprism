"""
Goal-Driven Trading OS — Backtester
回测引擎：运行策略 → 计算绩效 → 压力测试 → Walk-forward 验证
"""
import json
import math
import numpy as np
import pandas as pd
from datetime import datetime
import yaml

from market_data import fetch_stock_history, compute_technicals
from strategies.base import get_strategy, BacktestMetrics
from models import BacktestRun, StrategyConfig, UserGoals


CRISIS_PERIODS = [
    ("2008 金融危机", "2008-09-01", "2009-03-31"),
    ("2020 COVID 崩盘", "2020-02-15", "2020-04-15"),
    ("2022 加息风暴", "2022-01-01", "2022-10-31"),
]


def _simulate_portfolio(signals, df, initial_capital=10000, risk_per_trade=0.02) -> BacktestMetrics:
    """
    简单组合模拟器：按信号顺序执行交易
    """
    capital = initial_capital
    position = None
    trades = []
    equity = [capital]

    for sig in signals:
        price = sig.entry_price

        if sig.direction == "long" and position is None:
            risk_per_share = abs(price - sig.stop_loss) if sig.stop_loss else price * 0.02
            if risk_per_share == 0:
                continue
            risk_budget = capital * risk_per_trade
            shares = math.floor(risk_budget / risk_per_share)
            if shares <= 0:
                continue
            position = {"entry": price, "shares": shares, "stop": sig.stop_loss, "time": sig.timestamp}

        elif sig.direction == "close" and position is not None:
            pnl = (price - position["entry"]) * position["shares"]
            capital += pnl
            trades.append({
                "entry": position["entry"],
                "exit": price,
                "shares": position["shares"],
                "pnl": round(pnl, 2),
                "return_pct": round(pnl / (position["entry"] * position["shares"]), 4),
                "entry_time": str(position["time"]),
                "exit_time": str(sig.timestamp),
            })
            position = None

        equity.append(capital)

    if not trades:
        return BacktestMetrics(final_equity=capital, equity_curve=equity)

    wins = [t for t in trades if t["pnl"] > 0]
    losses = [t for t in trades if t["pnl"] <= 0]

    total_return = (capital - initial_capital) / initial_capital
    equity_series = pd.Series(equity)
    peak = equity_series.cummax()
    drawdowns = (equity_series - peak) / peak
    max_drawdown = float(drawdowns.min())

    trading_days = len(df)
    years = trading_days / 252 if trading_days > 0 else 1
    annual_return = (1 + total_return) ** (1 / years) - 1 if years > 0 else 0

    returns = equity_series.pct_change().dropna()
    sharpe = float(returns.mean() / returns.std() * np.sqrt(252)) if returns.std() > 0 else 0

    neg_returns = returns[returns < 0]
    sortino = float(returns.mean() / neg_returns.std() * np.sqrt(252)) if len(neg_returns) > 0 and neg_returns.std() > 0 else 0

    total_wins = sum(t["pnl"] for t in wins)
    total_losses = abs(sum(t["pnl"] for t in losses))
    profit_factor = total_wins / total_losses if total_losses > 0 else float("inf")

    return BacktestMetrics(
        total_return=round(total_return, 4),
        annual_return=round(annual_return, 4),
        max_drawdown=round(max_drawdown, 4),
        sharpe_ratio=round(sharpe, 2),
        sortino_ratio=round(sortino, 2),
        win_rate=round(len(wins) / len(trades), 4) if trades else 0,
        total_trades=len(trades),
        profit_factor=round(profit_factor, 2),
        avg_win=round(np.mean([t["pnl"] for t in wins]), 2) if wins else 0,
        avg_loss=round(np.mean([t["pnl"] for t in losses]), 2) if losses else 0,
        final_equity=round(capital, 2),
        equity_curve=equity,
        trades=trades,
    )


def run_full_backtest(config: StrategyConfig, goals: UserGoals = None, db=None) -> dict:
    """
    运行完整回测 + walk-forward 验证
    """
    strategy_cls = get_strategy(config.strategy_name)
    if not strategy_cls:
        return {"error": f"Strategy '{config.strategy_name}' not found"}

    params = yaml.safe_load(config.params_yaml) if config.params_yaml else {}
    strategy = strategy_cls(params)

    df = fetch_stock_history(config.symbol, period="5y")
    if df.empty:
        return {"error": f"No data for {config.symbol}"}

    df = compute_technicals(df)
    signals = strategy.generate_signals(df)

    for sig in signals:
        sig.symbol = config.symbol

    risk_per_trade = goals.risk_per_trade if goals else 0.02
    metrics = _simulate_portfolio(signals, df, risk_per_trade=risk_per_trade)

    # Walk-forward: 70/30 split
    split_idx = int(len(df) * 0.7)
    df_train = df.iloc[:split_idx]
    df_test = df.iloc[split_idx:]

    signals_train = strategy.generate_signals(df_train.copy())
    for s in signals_train:
        s.symbol = config.symbol
    metrics_train = _simulate_portfolio(signals_train, df_train, risk_per_trade=risk_per_trade)

    signals_test = strategy.generate_signals(df_test.copy())
    for s in signals_test:
        s.symbol = config.symbol
    metrics_test = _simulate_portfolio(signals_test, df_test, risk_per_trade=risk_per_trade)

    compatible = True
    if goals and metrics.max_drawdown < -goals.max_drawdown:
        compatible = False

    # Save to DB
    if db:
        run = BacktestRun(
            strategy_config_id=config.id,
            run_type="full",
            start_date=str(df.index[0].date()),
            end_date=str(df.index[-1].date()),
            total_return=metrics.total_return,
            annual_return=metrics.annual_return,
            max_drawdown=metrics.max_drawdown,
            sharpe_ratio=metrics.sharpe_ratio,
            sortino_ratio=metrics.sortino_ratio,
            win_rate=metrics.win_rate,
            total_trades=metrics.total_trades,
            profit_factor=metrics.profit_factor,
            trades_json=json.dumps(metrics.trades[:50]),
            compatible_with_goals=compatible,
        )
        db.add(run)
        db.commit()

    return {
        "metrics": metrics,
        "walk_forward": {
            "in_sample": metrics_train,
            "out_of_sample": metrics_test,
            "overfit_ratio": round(metrics_train.sharpe_ratio / metrics_test.sharpe_ratio, 2) if metrics_test.sharpe_ratio != 0 else float("inf"),
        },
        "compatible": compatible,
        "signals_count": len(signals),
    }


def run_stress_test(config: StrategyConfig, db=None) -> list[dict]:
    """
    压力测试：在极端历史时期运行策略
    """
    strategy_cls = get_strategy(config.strategy_name)
    if not strategy_cls:
        return [{"error": f"Strategy '{config.strategy_name}' not found"}]

    params = yaml.safe_load(config.params_yaml) if config.params_yaml else {}
    strategy = strategy_cls(params)
    results = []

    for label, start, end in CRISIS_PERIODS:
        df = fetch_stock_history(config.symbol, start=start, end=end)
        if df.empty or len(df) < 20:
            results.append({"period": label, "error": "Insufficient data"})
            continue

        df = compute_technicals(df)
        signals = strategy.generate_signals(df)
        for s in signals:
            s.symbol = config.symbol

        metrics = _simulate_portfolio(signals, df)

        if db:
            run = BacktestRun(
                strategy_config_id=config.id,
                run_type="stress_test",
                period_label=label,
                start_date=start,
                end_date=end,
                total_return=metrics.total_return,
                annual_return=metrics.annual_return,
                max_drawdown=metrics.max_drawdown,
                sharpe_ratio=metrics.sharpe_ratio,
                win_rate=metrics.win_rate,
                total_trades=metrics.total_trades,
                compatible_with_goals=None,
            )
            db.add(run)

        results.append({
            "period": label,
            "metrics": metrics,
        })

    if db:
        db.commit()

    return results
