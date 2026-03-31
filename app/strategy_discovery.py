"""
Goal-Driven Trading OS — AI Strategy Discovery
自动搜索和生成符合目标的策略，无需手动配置
"""
import json
import itertools
from datetime import datetime
from sqlalchemy.orm import Session

from strategies.base import get_all_strategies, BacktestMetrics
from market_data import fetch_stock_history, compute_technicals
from backtester import _simulate_portfolio, CRISIS_PERIODS
from models import UserGoals, StrategyConfig, BacktestRun, StrategyLeaderboard


# 每个策略的参数搜索空间
PARAM_SEARCH_SPACE = {
    "sma_crossover": [
        {"fast_period": 10, "slow_period": 30, "stop_loss_atr_mult": 2.0},
        {"fast_period": 10, "slow_period": 50, "stop_loss_atr_mult": 2.0},
        {"fast_period": 20, "slow_period": 50, "stop_loss_atr_mult": 2.0},
        {"fast_period": 20, "slow_period": 100, "stop_loss_atr_mult": 2.0},
        {"fast_period": 5, "slow_period": 20, "stop_loss_atr_mult": 1.5},
        {"fast_period": 50, "slow_period": 200, "stop_loss_atr_mult": 3.0},
    ],
    "rsi_momentum": [
        {"rsi_period": 14, "oversold": 30, "overbought": 70, "stop_loss_atr_mult": 1.5},
        {"rsi_period": 14, "oversold": 25, "overbought": 75, "stop_loss_atr_mult": 2.0},
        {"rsi_period": 7, "oversold": 20, "overbought": 80, "stop_loss_atr_mult": 1.5},
        {"rsi_period": 21, "oversold": 35, "overbought": 65, "stop_loss_atr_mult": 2.0},
        {"rsi_period": 10, "oversold": 30, "overbought": 70, "stop_loss_atr_mult": 1.0},
    ],
    "bollinger_reversion": [
        {"bb_period": 20, "bb_std": 2.0, "stop_loss_atr_mult": 1.5, "exit_at": "mid"},
        {"bb_period": 20, "bb_std": 2.0, "stop_loss_atr_mult": 1.5, "exit_at": "upper"},
        {"bb_period": 20, "bb_std": 2.5, "stop_loss_atr_mult": 2.0, "exit_at": "mid"},
        {"bb_period": 10, "bb_std": 1.5, "stop_loss_atr_mult": 1.0, "exit_at": "mid"},
        {"bb_period": 30, "bb_std": 2.0, "stop_loss_atr_mult": 2.0, "exit_at": "upper"},
    ],
}

# 常用标的列表
SYMBOLS = ["SPY", "QQQ", "IWM"]


def discover_strategies(goals: UserGoals, db: Session, symbols: list[str] = None, progress_callback=None) -> list[dict]:
    """
    AI 策略发现：自动搜索所有策略 × 参数 × 标的组合，
    找到符合用户目标的最佳策略

    流程:
    1. 遍历所有策略模板 × 参数组合 × 标的
    2. 对每个组合运行回测
    3. 过滤：历史最大回撤 ≤ 用户目标回撤
    4. 按 Sharpe 排序
    5. 返回 Top 10 + 自动保存最佳策略到数据库

    Returns: [{strategy_name, symbol, params, metrics, compatible, rank, recommendation}]
    """
    if symbols is None:
        symbols = SYMBOLS

    all_strategies = get_all_strategies()
    results = []
    total_combos = sum(len(PARAM_SEARCH_SPACE.get(name, [{}])) * len(symbols) for name in all_strategies)
    tested = 0

    for symbol in symbols:
        # 获取一次数据，所有策略共用
        df = fetch_stock_history(symbol, period="5y")
        if df.empty or len(df) < 50:
            continue
        df = compute_technicals(df)

        for strategy_name, strategy_cls in all_strategies.items():
            param_variants = PARAM_SEARCH_SPACE.get(strategy_name, [{}])

            for params in param_variants:
                tested += 1
                try:
                    strategy = strategy_cls(params)
                    signals = strategy.generate_signals(df.copy())
                    for s in signals:
                        s.symbol = symbol

                    metrics = _simulate_portfolio(
                        signals, df,
                        risk_per_trade=goals.risk_per_trade,
                    )

                    compatible = abs(metrics.max_drawdown) <= goals.max_drawdown
                    meets_return = metrics.annual_return >= goals.annual_return_target

                    if metrics.total_trades < 3:
                        recommendation = "交易次数太少，数据不足以判断"
                        quality = 0
                    elif compatible and meets_return:
                        recommendation = "强烈推荐：收益和回撤都符合你的目标"
                        quality = 3
                    elif compatible:
                        recommendation = "兼容：回撤在目标内，收益可能略低"
                        quality = 2
                    else:
                        recommendation = f"不兼容：回撤 {abs(metrics.max_drawdown)*100:.1f}% 超过目标 {goals.max_drawdown*100:.1f}%"
                        quality = 1 if metrics.sharpe_ratio > 0 else 0

                    # 生成参数描述（用户友好）
                    param_desc = _describe_params(strategy_name, params)

                    results.append({
                        "strategy_name": strategy_name,
                        "strategy_desc": strategy_cls.description,
                        "symbol": symbol,
                        "params": params,
                        "param_desc": param_desc,
                        "metrics": metrics,
                        "compatible": compatible,
                        "meets_return": meets_return,
                        "quality": quality,
                        "recommendation": recommendation,
                    })
                except Exception as e:
                    continue

    # 排序：quality 降序 → Sharpe 降序
    results.sort(key=lambda x: (x["quality"], x["metrics"].sharpe_ratio), reverse=True)

    # 标排名
    for i, r in enumerate(results):
        r["rank"] = i + 1

    # 自动保存 Top 3 兼容策略到数据库
    saved_count = 0
    for r in results[:10]:
        if r["compatible"] and r["metrics"].total_trades >= 3 and saved_count < 3:
            existing = db.query(StrategyConfig).filter(
                StrategyConfig.strategy_name == r["strategy_name"],
                StrategyConfig.symbol == r["symbol"],
                StrategyConfig.params_yaml == json.dumps(r["params"]),
            ).first()

            if not existing:
                config = StrategyConfig(
                    strategy_name=r["strategy_name"],
                    symbol=r["symbol"],
                    params_yaml=json.dumps(r["params"]),
                    is_active=True,
                )
                db.add(config)

                run = BacktestRun(
                    strategy_config_id=0,  # will be updated
                    run_type="discovery",
                    period_label=f"AI发现 #{r['rank']}",
                    start_date=str(datetime.now().date()),
                    total_return=r["metrics"].total_return,
                    annual_return=r["metrics"].annual_return,
                    max_drawdown=r["metrics"].max_drawdown,
                    sharpe_ratio=r["metrics"].sharpe_ratio,
                    win_rate=r["metrics"].win_rate,
                    total_trades=r["metrics"].total_trades,
                    profit_factor=r["metrics"].profit_factor,
                    compatible_with_goals=True,
                )
                db.add(run)
                saved_count += 1
                r["auto_saved"] = True

    if saved_count > 0:
        db.commit()

    return {
        "results": results[:20],
        "total_tested": tested,
        "total_compatible": sum(1 for r in results if r["compatible"]),
        "auto_saved": saved_count,
    }


def _describe_params(strategy_name: str, params: dict) -> str:
    """生成用户友好的参数描述"""
    if strategy_name == "sma_crossover":
        return f"{params.get('fast_period', 20)}日均线 × {params.get('slow_period', 50)}日均线"
    elif strategy_name == "rsi_momentum":
        return f"RSI({params.get('rsi_period', 14)}) 超卖{params.get('oversold', 30)}/超买{params.get('overbought', 70)}"
    elif strategy_name == "bollinger_reversion":
        exit_label = "中轨" if params.get("exit_at") == "mid" else "上轨"
        return f"布林带({params.get('bb_period', 20)}, {params.get('bb_std', 2.0)}倍) 出场:{exit_label}"
    return str(params)
