"""
Goal-Driven Trading OS — Risk Engine
组合风险计算 + 市场环境检测 + 跨市场关联
"""
import numpy as np
from sqlalchemy.orm import Session
from models import Position, UserGoals, MarketDataCache
from market_data import detect_market_regime, fetch_current_price


def compute_portfolio_risk(db: Session) -> dict:
    """
    计算当前组合风险

    Returns: {total_risk_pct, max_single_risk, current_drawdown, drawdown_headroom, regime, positions_at_risk}
    """
    goals = db.query(UserGoals).first()
    positions = db.query(Position).filter(Position.is_open == True).all()
    regime = detect_market_regime()

    if not positions:
        return {
            "total_risk_pct": 0,
            "max_single_risk": 0,
            "current_drawdown": 0,
            "drawdown_limit": goals.max_drawdown if goals else 0.10,
            "drawdown_headroom": goals.max_drawdown if goals else 0.10,
            "regime": regime,
            "positions_at_risk": [],
            "position_count": 0,
            "max_positions": goals.max_positions if goals else 0,
        }

    total_risk = sum(p.risk_pct_of_account or 0 for p in positions)
    max_single = max((p.risk_pct_of_account or 0) for p in positions) if positions else 0

    # Estimate current drawdown from unrealized PnL
    total_unrealized = sum(p.unrealized_pnl or 0 for p in positions)
    total_value = sum((p.account_balance_at_entry or 10000) for p in positions[:1])  # rough estimate
    current_drawdown = abs(total_unrealized / total_value) if total_value > 0 and total_unrealized < 0 else 0

    drawdown_limit = goals.max_drawdown if goals else 0.10
    headroom = drawdown_limit - current_drawdown

    # Positions at risk: those with risk > 3% of account
    at_risk = [
        {"symbol": p.symbol, "risk_pct": p.risk_pct_of_account, "unrealized_pnl": p.unrealized_pnl}
        for p in positions
        if (p.risk_pct_of_account or 0) > 0.03
    ]

    return {
        "total_risk_pct": round(total_risk, 4),
        "max_single_risk": round(max_single, 4),
        "current_drawdown": round(current_drawdown, 4),
        "drawdown_limit": drawdown_limit,
        "drawdown_headroom": round(headroom, 4),
        "regime": regime,
        "positions_at_risk": at_risk,
        "position_count": len(positions),
        "max_positions": goals.max_positions if goals else 0,
    }


def compute_cross_market_correlation(db: Session, lookback_days: int = 90) -> dict:
    """
    计算跨市场关联性 (需要 MarketDataCache 有数据)

    Returns: {correlation_matrix, assets}
    """
    from datetime import datetime, timedelta
    cutoff = datetime.utcnow() - timedelta(days=lookback_days)

    cache_entries = db.query(MarketDataCache).filter(
        MarketDataCache.date >= cutoff,
    ).all()

    if not cache_entries:
        return {"correlation_matrix": {}, "assets": [], "message": "数据不足，需要积累至少 30 天的数据"}

    # Group by symbol
    data = {}
    for entry in cache_entries:
        if entry.symbol not in data:
            data[entry.symbol] = []
        data[entry.symbol].append({"date": entry.date, "close": entry.close})

    if len(data) < 2:
        return {"correlation_matrix": {}, "assets": list(data.keys()), "message": "需要至少 2 个品种的数据"}

    # Build returns DataFrame
    import pandas as pd
    returns = {}
    for symbol, entries in data.items():
        df = pd.DataFrame(entries).sort_values("date").set_index("date")
        returns[symbol] = df["close"].pct_change().dropna()

    returns_df = pd.DataFrame(returns).dropna()
    if returns_df.empty or len(returns_df) < 10:
        return {"correlation_matrix": {}, "assets": list(data.keys()), "message": "数据点不足 (需要至少 10 天)"}

    corr = returns_df.corr()
    return {
        "correlation_matrix": corr.to_dict(),
        "assets": list(corr.columns),
    }
