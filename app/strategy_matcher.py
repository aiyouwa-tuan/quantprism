"""
Goal-Driven Trading OS — Strategy Matcher
根据用户目标自动匹配和排序策略
"""
from datetime import datetime
import yaml

from strategies.base import get_all_strategies, BacktestMetrics
from market_data import fetch_stock_history, compute_technicals, detect_market_regime
from backtester import _simulate_portfolio
from models import UserGoals, StrategyConfig, StrategyLeaderboard


def match_strategies_to_goals(goals: UserGoals, db, symbol: str = "SPY") -> list[dict]:
    """
    对每个注册策略运行回测，检查是否兼容用户目标

    Returns sorted list: [{strategy_name, compatible, metrics, drawdown_headroom, recommendation}]
    """
    all_strategies = get_all_strategies()
    if not all_strategies:
        return []

    df = fetch_stock_history(symbol, period="5y")
    if df.empty:
        return [{"error": "No market data available"}]

    df = compute_technicals(df)
    results = []

    for name, strategy_cls in all_strategies.items():
        strategy = strategy_cls()
        signals = strategy.generate_signals(df.copy())
        for s in signals:
            s.symbol = symbol

        metrics = _simulate_portfolio(signals, df, risk_per_trade=goals.risk_per_trade)

        compatible = abs(metrics.max_drawdown) <= goals.max_drawdown
        drawdown_headroom = goals.max_drawdown - abs(metrics.max_drawdown)

        if compatible and metrics.annual_return >= goals.annual_return_target:
            recommendation = "强烈推荐：收益和回撤都在目标范围内"
        elif compatible:
            recommendation = "兼容：回撤在目标内，但收益可能不达标"
        else:
            recommendation = f"不兼容：历史最大回撤 {abs(metrics.max_drawdown)*100:.1f}% 超过你的 {goals.max_drawdown*100:.1f}% 目标"

        results.append({
            "strategy_name": name,
            "description": strategy_cls.description,
            "compatible": compatible,
            "metrics": metrics,
            "drawdown_headroom": round(drawdown_headroom, 4),
            "recommendation": recommendation,
        })

    results.sort(key=lambda x: (x["compatible"], x["metrics"].sharpe_ratio), reverse=True)
    return results


def refresh_leaderboard(db, symbol: str = "SPY"):
    """
    刷新策略排行榜：按市场环境分别回测
    """
    all_strategies = get_all_strategies()
    df_full = fetch_stock_history(symbol, start="2015-01-01", end=datetime.now().strftime("%Y-%m-%d"))
    if df_full.empty:
        return

    df_full = compute_technicals(df_full)

    # 按 VIX regime 分段 (简化：用整段数据的 regime 分类)
    regimes = {
        "low_vol": df_full[df_full.get("rsi_14", 50) < 50].copy() if "rsi_14" in df_full.columns else df_full.copy(),
        "mid_vol": df_full.copy(),
        "high_vol": df_full.copy(),
    }

    # 清除旧排行榜
    db.query(StrategyLeaderboard).delete()

    for name, strategy_cls in all_strategies.items():
        strategy = strategy_cls()
        signals = strategy.generate_signals(df_full.copy())
        for s in signals:
            s.symbol = symbol

        metrics = _simulate_portfolio(signals, df_full)

        regime = detect_market_regime()
        entry = StrategyLeaderboard(
            strategy_name=name,
            regime=regime["regime"],
            sharpe_ratio=metrics.sharpe_ratio,
            annual_return=metrics.annual_return,
            max_drawdown=metrics.max_drawdown,
            win_rate=metrics.win_rate,
            total_trades=metrics.total_trades,
        )
        db.add(entry)

    db.commit()
