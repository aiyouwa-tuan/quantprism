"""
Goal-Driven Trading OS — Backtester v2
回测引擎：滑点模型 + 佣金模型 + Walk-forward + 压力测试 + 统计报告
"""
import json
import math
import numpy as np
import pandas as pd
from datetime import datetime
from dataclasses import dataclass
import yaml

from market_data import fetch_stock_history, compute_technicals
from strategies.base import get_strategy, BacktestMetrics
from models import BacktestRun, StrategyConfig, UserGoals


CRISIS_PERIODS = [
    ("2008 金融危机", "2008-09-01", "2009-03-31"),
    ("2020 COVID 崩盘", "2020-02-15", "2020-04-15"),
    ("2022 加息风暴", "2022-01-01", "2022-10-31"),
    ("2023 银行危机", "2023-03-01", "2023-05-31"),
]


# ========== 成本模型 ==========

@dataclass
class CostModel:
    """交易成本模型：滑点 + 佣金"""
    slippage_pct: float = 0.0005          # 0.05% 默认滑点
    stock_commission_per_share: float = 0.005   # IBKR tiered: $0.005/股
    stock_min_commission: float = 1.0
    option_commission_per_contract: float = 0.65
    option_min_commission: float = 1.0
    asset_type: str = "stock"

    def apply_slippage(self, price: float, direction: str) -> float:
        """买入向上滑，卖出向下滑"""
        if direction == "long":
            return price * (1 + self.slippage_pct)
        return price * (1 - self.slippage_pct)

    def calc_commission(self, quantity: float) -> float:
        if self.asset_type == "option":
            return max(quantity * self.option_commission_per_contract, self.option_min_commission)
        return max(quantity * self.stock_commission_per_share, self.stock_min_commission)


COST_MODELS = {
    "zero": CostModel(slippage_pct=0, stock_commission_per_share=0, stock_min_commission=0),
    "low": CostModel(slippage_pct=0.0003, stock_commission_per_share=0.003),
    "default": CostModel(),
    "high": CostModel(slippage_pct=0.001, stock_commission_per_share=0.01),
    "option": CostModel(slippage_pct=0.002, asset_type="option"),
}


def _simulate_portfolio(signals, df, initial_capital=10000, risk_per_trade=0.02,
                        cost_model: CostModel = None, collect_daily=False) -> BacktestMetrics:
    """
    组合模拟器 v2：滑点 + 佣金 + 净收益计算
    """
    if cost_model is None:
        cost_model = COST_MODELS["default"]

    capital = initial_capital
    position = None
    trades = []
    equity = [capital]
    daily_details = []
    total_commission = 0
    total_slippage_cost = 0

    # Build signal lookup by date for daily detail
    sig_by_date = {}
    for sig in signals:
        try:
            d = pd.Timestamp(sig.timestamp).strftime('%Y-%m-%d')
            sig_by_date[d] = sig.direction
        except Exception:
            pass

    for sig in signals:
        raw_price = sig.entry_price

        if sig.direction == "long" and position is None:
            fill_price = cost_model.apply_slippage(raw_price, "long")
            slip = (fill_price - raw_price)

            risk_per_share = abs(fill_price - sig.stop_loss) if sig.stop_loss else fill_price * 0.02
            if risk_per_share == 0:
                continue
            risk_budget = capital * risk_per_trade
            shares = math.floor(risk_budget / risk_per_share)
            if shares <= 0:
                continue

            commission = cost_model.calc_commission(shares)
            capital -= commission
            total_commission += commission
            total_slippage_cost += abs(slip) * shares

            position = {
                "entry": fill_price, "shares": shares, "stop": sig.stop_loss,
                "time": sig.timestamp, "comm_in": commission,
            }

        elif sig.direction == "close" and position is not None:
            fill_price = cost_model.apply_slippage(raw_price, "close")
            slip = (raw_price - fill_price)

            commission = cost_model.calc_commission(position["shares"])
            capital -= commission
            total_commission += commission
            total_slippage_cost += abs(slip) * position["shares"]

            gross_pnl = (fill_price - position["entry"]) * position["shares"]
            net_pnl = gross_pnl - position.get("comm_in", 0) - commission
            capital += gross_pnl

            trades.append({
                "entry": round(position["entry"], 2),
                "exit": round(fill_price, 2),
                "shares": position["shares"],
                "gross_pnl": round(gross_pnl, 2),
                "pnl": round(net_pnl, 2),
                "commission": round(position.get("comm_in", 0) + commission, 2),
                "return_pct": round(gross_pnl / (position["entry"] * position["shares"]), 4) if position["entry"] else 0,
                "entry_time": str(position["time"]),
                "exit_time": str(sig.timestamp),
            })
            position = None

        equity.append(capital)

    # Generate daily details from df + equity curve + signals
    if collect_daily and not df.empty:
        peak_val = initial_capital
        eq_idx = 0
        for i, (date, row) in enumerate(df.iterrows()):
            eq_val = equity[min(eq_idx, len(equity)-1)]
            peak_val = max(peak_val, eq_val)
            dd_pct = (eq_val / peak_val - 1) * 100 if peak_val > 0 else 0
            date_str = date.strftime('%Y-%m-%d') if hasattr(date, 'strftime') else str(date)[:10]
            daily_details.append({
                "date": date_str,
                "open": round(float(row.get("open", 0)), 2),
                "high": round(float(row.get("high", 0)), 2),
                "low": round(float(row.get("low", 0)), 2),
                "close": round(float(row.get("close", 0)), 2),
                "volume": int(row.get("volume", 0)),
                "equity": round(eq_val, 2),
                "drawdown_pct": round(dd_pct, 2),
                "signal": sig_by_date.get(date_str, None),
                "position": "long" if position else None,
            })
            # Advance equity index when we have trade signals
            if date_str in sig_by_date:
                eq_idx += 1

    if not trades:
        return BacktestMetrics(final_equity=round(capital, 2), equity_curve=equity, daily_details=daily_details if collect_daily else None)

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

    # 连续亏损统计
    max_consecutive_losses = 0
    current_streak = 0
    for t in trades:
        if t["pnl"] <= 0:
            current_streak += 1
            max_consecutive_losses = max(max_consecutive_losses, current_streak)
        else:
            current_streak = 0

    # 持有天数统计
    holding_days = []
    for t in trades:
        try:
            d = (pd.Timestamp(t["exit_time"]) - pd.Timestamp(t["entry_time"])).days
            holding_days.append(d)
        except Exception:
            pass
    avg_holding_days = round(np.mean(holding_days), 1) if holding_days else 0

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
        max_consecutive_losses=max_consecutive_losses,
        avg_holding_days=avg_holding_days,
        daily_details=daily_details if collect_daily else None,
    )


def generate_backtest_report(metrics: BacktestMetrics, cost_model: CostModel = None) -> dict:
    """
    生成回测统计报告（用于 UI 展示）
    """
    if cost_model is None:
        cost_model = COST_MODELS["default"]

    total_commission = sum(t.get("commission", 0) for t in (metrics.trades or []))
    gross_pnl = sum(t.get("gross_pnl", 0) for t in (metrics.trades or []))

    # 月度收益分组
    monthly = {}
    for t in (metrics.trades or []):
        try:
            month = str(t["exit_time"])[:7]
            monthly[month] = monthly.get(month, 0) + t["pnl"]
        except Exception:
            pass

    # 连续亏损
    max_consecutive_losses = 0
    streak = 0
    for t in (metrics.trades or []):
        if t["pnl"] <= 0:
            streak += 1
            max_consecutive_losses = max(max_consecutive_losses, streak)
        else:
            streak = 0

    return {
        "total_return_pct": round(metrics.total_return * 100, 2),
        "annual_return_pct": round(metrics.annual_return * 100, 2),
        "max_drawdown_pct": round(metrics.max_drawdown * 100, 2),
        "sharpe": metrics.sharpe_ratio,
        "sortino": metrics.sortino_ratio,
        "win_rate_pct": round(metrics.win_rate * 100, 1),
        "total_trades": metrics.total_trades,
        "profit_factor": metrics.profit_factor,
        "avg_win": metrics.avg_win,
        "avg_loss": metrics.avg_loss,
        "gross_pnl": round(gross_pnl, 2),
        "total_commission": round(total_commission, 2),
        "net_pnl": round(gross_pnl - total_commission, 2),
        "cost_model": f"滑点 {cost_model.slippage_pct*100:.2f}% + 佣金 ${cost_model.stock_commission_per_share}/股",
        "max_consecutive_losses": max_consecutive_losses,
        "monthly_returns": [{"month": k, "pnl": round(v, 2)} for k, v in sorted(monthly.items())],
        "equity_curve": metrics.equity_curve,
    }


def run_full_backtest(config: StrategyConfig, goals: UserGoals = None, db=None,
                      cost_model_name: str = "default",
                      start_date: str = None, end_date: str = None,
                      collect_daily: bool = True) -> dict:
    """
    运行完整回测 + walk-forward 验证 + 成本模型
    """
    strategy_cls = get_strategy(config.strategy_name)
    if not strategy_cls:
        return {"error": f"Strategy '{config.strategy_name}' not found"}

    params = yaml.safe_load(config.params_yaml) if config.params_yaml else {}
    strategy = strategy_cls(params)
    cost_model = COST_MODELS.get(cost_model_name, COST_MODELS["default"])

    # 根据 instrument 选择成本模型
    if config.instrument in ("sell_put", "covered_call", "call", "put"):
        cost_model = COST_MODELS["option"]

    symbol = config.symbol_pool.split(",")[0].strip() if config.symbol_pool else "SPY"

    # Support custom date range (up to 20+ years via yfinance max)
    if start_date and end_date:
        df = fetch_stock_history(symbol, start=start_date, end=end_date)
    elif start_date:
        df = fetch_stock_history(symbol, start=start_date, end=datetime.now().strftime('%Y-%m-%d'))
    else:
        df = fetch_stock_history(symbol, period="5y")

    if df.empty:
        return {"error": f"No data for {symbol}"}

    df = compute_technicals(df)
    signals = strategy.generate_signals(df)
    for sig in signals:
        sig.symbol = symbol

    risk_per_trade = goals.risk_per_trade if goals else 0.02
    if risk_per_trade < 0.005:  # sanity check: at least 0.5%
        risk_per_trade = 0.02
    metrics = _simulate_portfolio(signals, df, risk_per_trade=risk_per_trade, cost_model=cost_model, collect_daily=collect_daily)

    # Walk-forward: 70/30
    split_idx = int(len(df) * 0.7)
    df_train = df.iloc[:split_idx]
    df_test = df.iloc[split_idx:]

    signals_train = strategy.generate_signals(df_train.copy())
    for s in signals_train:
        s.symbol = symbol
    metrics_train = _simulate_portfolio(signals_train, df_train, risk_per_trade=risk_per_trade, cost_model=cost_model)

    signals_test = strategy.generate_signals(df_test.copy())
    for s in signals_test:
        s.symbol = symbol
    metrics_test = _simulate_portfolio(signals_test, df_test, risk_per_trade=risk_per_trade, cost_model=cost_model)

    compatible = True
    if goals and metrics.max_drawdown < -goals.max_drawdown:
        compatible = False

    report = generate_backtest_report(metrics, cost_model)

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
        "report": report,
        "walk_forward": {
            "in_sample": metrics_train,
            "out_of_sample": metrics_test,
            "overfit_ratio": round(metrics_train.sharpe_ratio / metrics_test.sharpe_ratio, 2) if metrics_test.sharpe_ratio != 0 else float("inf"),
        },
        "compatible": compatible,
        "signals_count": len(signals),
        "cost_model": cost_model,
    }


def run_stress_test(config: StrategyConfig, db=None) -> list:
    """压力测试：在极端历史时期运行策略"""
    strategy_cls = get_strategy(config.strategy_name)
    if not strategy_cls:
        return [{"error": f"Strategy '{config.strategy_name}' not found"}]

    params = yaml.safe_load(config.params_yaml) if config.params_yaml else {}
    strategy = strategy_cls(params)
    cost_model = COST_MODELS["default"]
    results = []

    symbol = config.symbol_pool.split(",")[0].strip() if config.symbol_pool else "SPY"

    for label, start, end in CRISIS_PERIODS:
        df = fetch_stock_history(symbol, start=start, end=end)
        if df.empty or len(df) < 20:
            results.append({"period": label, "error": "Insufficient data"})
            continue

        df = compute_technicals(df)
        signals = strategy.generate_signals(df)
        for s in signals:
            s.symbol = symbol

        metrics = _simulate_portfolio(signals, df, cost_model=cost_model)

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

        results.append({"period": label, "metrics": metrics})

    if db:
        db.commit()

    return results
