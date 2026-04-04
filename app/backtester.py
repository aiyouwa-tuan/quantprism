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


def _resolve_strategy(config: StrategyConfig):
    """Return (strategy_cls, proxy_note). Falls back to a built-in if custom strategy has no code."""
    cls = get_strategy(config.strategy_name)
    if cls:
        return cls, None
    desc = ((config.description or "") + " " + (config.strategy_name or "")).lower()
    if any(k in desc for k in ("reversion", "mean", "bollinger", "均值", "回归")):
        fallback, label = "bollinger_reversion", "布林带均值回归"
    elif any(k in desc for k in ("rsi", "momentum", "动量", "趋势", "breaker", "surge", "acceleration")):
        fallback, label = "rsi_momentum", "RSI动量"
    else:
        fallback, label = "sma_crossover", "SMA双均线"
    fallback_cls = get_strategy(fallback)
    note = f"AI策略「{config.display_name or config.strategy_name}」尚无实际交易代码，以「{label}」策略作参考代理回测，结果仅供参考"
    return fallback_cls, note


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
                "capital_before": capital,
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

            entry_date_str = str(position["time"])[:10]
            exit_date_str = str(sig.timestamp)[:10]
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
                "entry_date": entry_date_str,
                "exit_date": exit_date_str,
                "capital_before": position.get("capital_before", 0),
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

    # ═══ Phase 1 Enhanced Metrics ═══

    # Calmar Ratio = annual_return / |max_drawdown|
    calmar = round(annual_return / abs(max_drawdown), 2) if max_drawdown != 0 else 0

    # SQN = (mean_trade_return / std_trade_return) * sqrt(total_trades)
    trade_returns = [t.get("return_pct", 0) for t in trades]
    sqn = 0
    sqn_grade = "N/A"
    if len(trade_returns) > 1 and np.std(trade_returns) > 0:
        sqn = round(float(np.mean(trade_returns) / np.std(trade_returns) * np.sqrt(len(trade_returns))), 2)
    if sqn >= 5.0:
        sqn_grade = "卓越"
    elif sqn >= 3.0:
        sqn_grade = "优"
    elif sqn >= 2.0:
        sqn_grade = "良"
    elif sqn >= 1.6:
        sqn_grade = "可"
    else:
        sqn_grade = "差"

    # Best / Worst / Avg single trade return
    best_trade = round(max(trade_returns) * 100, 2) if trade_returns else 0
    worst_trade = round(min(trade_returns) * 100, 2) if trade_returns else 0
    avg_trade_return = round(float(np.mean(trade_returns)) * 100, 2) if trade_returns else 0

    # Rolling metrics (126-day / 6-month window)
    rolling_sharpe_data = []
    rolling_sortino_data = []
    rolling_vol_data = []
    window = 126
    if len(returns) > window:
        for i in range(window, len(returns)):
            chunk = returns.iloc[i - window:i]
            rs = float(chunk.mean() / chunk.std() * np.sqrt(252)) if chunk.std() > 0 else 0
            neg_c = chunk[chunk < 0]
            rso = float(chunk.mean() / neg_c.std() * np.sqrt(252)) if len(neg_c) > 0 and neg_c.std() > 0 else 0
            rv = float(chunk.std() * np.sqrt(252) * 100)
            # Approximate date from daily_details
            date_str = daily_details[min(i, len(daily_details) - 1)]["date"] if daily_details and i < len(daily_details) else ""
            rolling_sharpe_data.append({"date": date_str, "value": round(rs, 2)})
            rolling_sortino_data.append({"date": date_str, "value": round(rso, 2)})
            rolling_vol_data.append({"date": date_str, "value": round(rv, 1)})

    # ═══ Phase 2: Advanced Statistics ═══

    # VaR 95% + CVaR 95% (Historical Percentile)
    var_95 = 0.0
    cvar_95 = 0.0
    if len(returns) > 20:
        var_95 = round(float(np.percentile(returns, 5)) * 100, 4)
        tail = returns[returns <= np.percentile(returns, 5)]
        cvar_95 = round(float(tail.mean()) * 100, 4) if len(tail) > 0 else var_95

    # Omega Ratio (probability-weighted gains vs losses, threshold=0)
    omega_val = 0.0
    if len(returns) > 10:
        excess = returns - 0.0
        gains_sum = float(excess[excess > 0].sum())
        losses_abs = float(abs(excess[excess <= 0].sum()))
        omega_val = round(gains_sum / losses_abs, 2) if losses_abs > 0 else 99.0

    # PSR (Probabilistic Sharpe Ratio) — Bailey-Lopez de Prado
    psr_val = 0.0
    if len(returns) > 30:
        from scipy.stats import norm as _norm
        n = len(returns)
        sr = sharpe
        skew_val = float(returns.skew())
        kurt_val = float(returns.kurtosis())
        sr_std = math.sqrt((1 + 0.5 * sr**2 - skew_val * sr + ((kurt_val) / 4) * sr**2) / max(n - 1, 1))
        if sr_std > 0:
            psr_val = round(float(_norm.cdf(sr / sr_std)), 4)

    # Kelly Criterion (Full + Half)
    kelly_full = 0.0
    kelly_half = 0.0
    win_rate_val = len(wins) / len(trades) if trades else 0
    if win_rate_val > 0 and len(losses) > 0:
        avg_w = float(np.mean([abs(t["pnl"]) for t in wins])) if wins else 0
        avg_l = float(np.mean([abs(t["pnl"]) for t in losses])) if losses else 1
        if avg_l > 0:
            b = avg_w / avg_l  # win/loss ratio
            kelly_full = round(float(win_rate_val - (1 - win_rate_val) / b), 4) if b > 0 else 0
            kelly_half = round(kelly_full / 2, 4)
            kelly_full = max(kelly_full, 0)
            kelly_half = max(kelly_half, 0)

    # Monte Carlo (1000 paths, 252-day bootstrap projection)
    monte_carlo_data = {}
    if len(returns) > 30:
        n_paths = 1000
        n_days = 252
        ret_arr = returns.values
        rng = np.random.default_rng(42)
        paths = np.zeros((n_paths, n_days + 1))
        paths[:, 0] = capital
        for p in range(n_paths):
            sampled = rng.choice(ret_arr, size=n_days, replace=True)
            paths[p, 1:] = capital * np.cumprod(1 + sampled)
        final_vals = paths[:, -1]
        # Sample 20 representative paths, downsample to 50 points
        sample_idx = np.linspace(0, n_paths - 1, 20, dtype=int)
        step_size = max(1, n_days // 50)
        sampled_paths = []
        for idx in sample_idx:
            sampled_paths.append([round(float(v), 2) for v in paths[idx, ::step_size]])
        # Percentile bands (50 points each)
        p5_line = [round(float(v), 2) for v in np.percentile(paths, 5, axis=0)[::step_size]]
        p25_line = [round(float(v), 2) for v in np.percentile(paths, 25, axis=0)[::step_size]]
        p50_line = [round(float(v), 2) for v in np.percentile(paths, 50, axis=0)[::step_size]]
        p75_line = [round(float(v), 2) for v in np.percentile(paths, 75, axis=0)[::step_size]]
        p95_line = [round(float(v), 2) for v in np.percentile(paths, 95, axis=0)[::step_size]]
        monte_carlo_data = {
            "p5_final": round(float(np.percentile(final_vals, 5)), 2),
            "p50_final": round(float(np.median(final_vals)), 2),
            "p95_final": round(float(np.percentile(final_vals, 95)), 2),
            "mean_final": round(float(np.mean(final_vals)), 2),
            "p5_return": round(float((np.percentile(final_vals, 5) / capital - 1) * 100), 1),
            "p50_return": round(float((np.median(final_vals) / capital - 1) * 100), 1),
            "p95_return": round(float((np.percentile(final_vals, 95) / capital - 1) * 100), 1),
            "paths": sampled_paths,
            "p5_line": p5_line, "p25_line": p25_line, "p50_line": p50_line,
            "p75_line": p75_line, "p95_line": p95_line,
            "n_days": n_days,
            "start_equity": round(capital, 2),
        }

    # Trading Time Heatmap (by day-of-week × month)
    trade_heatmap = []
    if trades:
        hm_data = {}
        for t in trades:
            try:
                exit_dt = pd.Timestamp(t.get("exit_time", ""))
                dow = int(exit_dt.dayofweek)   # 0=Mon, 4=Fri
                month = int(exit_dt.month)     # 1-12
                key = (dow, month)
                if key not in hm_data:
                    hm_data[key] = []
                hm_data[key].append(t.get("return_pct", 0))
            except Exception:
                pass
        for (dow, month), rets in hm_data.items():
            trade_heatmap.append({
                "dow": dow, "month": month,
                "avg_return": round(float(np.mean(rets)) * 100, 2),
                "count": len(rets),
            })

    # MAE/MFE per trade (scan OHLC High/Low during open periods)
    trade_details = []
    for t in trades:
        entry_date = t.get("entry_date", "")
        exit_date = t.get("exit_date", "")
        entry_price = t.get("entry", 0)
        if entry_price == 0 or not entry_date or not exit_date:
            trade_details.append({**t, "mae": 0, "mfe": 0})
            continue
        try:
            mask = (df.index >= pd.Timestamp(entry_date)) & (df.index <= pd.Timestamp(exit_date))
            trade_df = df.loc[mask]
            if trade_df.empty:
                trade_details.append({**t, "mae": 0, "mfe": 0})
                continue
            lowest = float(trade_df["low"].min()) if "low" in trade_df.columns else entry_price
            highest = float(trade_df["high"].max()) if "high" in trade_df.columns else entry_price
            mae = round((lowest - entry_price) / entry_price * 100, 2)  # negative = adverse
            mfe = round((highest - entry_price) / entry_price * 100, 2)  # positive = favorable
            trade_details.append({**t, "mae": mae, "mfe": mfe})
        except Exception:
            trade_details.append({**t, "mae": 0, "mfe": 0})

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
        calmar_ratio=calmar,
        sqn_score=sqn,
        sqn_grade=sqn_grade,
        best_trade=best_trade,
        worst_trade=worst_trade,
        avg_trade_return=avg_trade_return,
        rolling_sharpe=rolling_sharpe_data,
        rolling_sortino=rolling_sortino_data,
        rolling_volatility=rolling_vol_data,
        trade_details=trade_details,
        var_95=var_95,
        cvar_95=cvar_95,
        omega_ratio=omega_val,
        psr=psr_val,
        kelly_full=kelly_full,
        kelly_half=kelly_half,
        monte_carlo=monte_carlo_data,
        trade_heatmap=trade_heatmap,
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
                      collect_daily: bool = True,
                      preloaded_df: pd.DataFrame = None) -> dict:
    """
    运行完整回测 + walk-forward 验证 + 成本模型
    """
    strategy_cls, proxy_note = _resolve_strategy(config)
    if not strategy_cls:
        return {"error": f"Strategy '{config.strategy_name}' not found"}

    params = yaml.safe_load(config.params_yaml) if config.params_yaml else {}
    strategy = strategy_cls(params)
    cost_model = COST_MODELS.get(cost_model_name, COST_MODELS["default"])

    # 根据 instrument 选择成本模型
    if config.instrument in ("sell_put", "covered_call", "call", "put"):
        cost_model = COST_MODELS["option"]

    symbol = config.symbol_pool.split(",")[0].strip() if config.symbol_pool else "SPY"

    # Use preloaded data if available (for parallel backtest optimization)
    if preloaded_df is not None and not preloaded_df.empty:
        df = preloaded_df.copy()
    elif start_date and end_date:
        df = fetch_stock_history(symbol, start=start_date, end=end_date)
    elif start_date:
        df = fetch_stock_history(symbol, start=start_date, end=datetime.now().strftime('%Y-%m-%d'))
    else:
        df = fetch_stock_history(symbol, period="5y")

    if df.empty:
        return {"error": f"No data for {symbol}"}

    if preloaded_df is None:
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
    if goals and goals.max_drawdown is not None and metrics.max_drawdown < -goals.max_drawdown:
        compatible = False
    if goals and goals.annual_return_target is not None and metrics.annual_return < goals.annual_return_target:
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

    result = {
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
    if proxy_note:
        result["proxy_note"] = proxy_note
    return result


def run_stress_test(config: StrategyConfig, db=None) -> list:
    """压力测试：在极端历史时期运行策略"""
    strategy_cls, _ = _resolve_strategy(config)
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
