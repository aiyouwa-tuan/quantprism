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
            "vix": regime.get("vix", 0),
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
        "vix": regime.get("vix", 0),
        "positions_at_risk": at_risk,
        "position_count": len(positions),
        "max_positions": goals.max_positions if goals else 0,
    }


def compute_sector_exposure(db: Session) -> dict:
    """计算行业暴露度"""
    positions = db.query(Position).filter(Position.is_open == True).all()
    if not positions:
        return {"sectors": {}, "total_value": 0, "warnings": []}

    # Simple sector mapping by symbol (could be enhanced with real sector data)
    SECTOR_MAP = {
        "AAPL": "科技", "MSFT": "科技", "NVDA": "科技", "GOOGL": "科技", "META": "科技",
        "AMZN": "消费", "TSLA": "消费", "HD": "消费", "COST": "消费", "NKE": "消费",
        "JPM": "金融", "BAC": "金融", "GS": "金融", "V": "金融", "MA": "金融",
        "JNJ": "医疗", "UNH": "医疗", "PFE": "医疗", "ABBV": "医疗", "MRK": "医疗",
        "XOM": "能源", "CVX": "能源", "COP": "能源",
        "SPY": "指数", "QQQ": "指数", "DIA": "指数", "IWM": "指数",
    }

    sector_values = {}
    total_value = 0
    for p in positions:
        value = abs((p.quantity or 0) * (p.current_price or p.entry_price or 0))
        total_value += value
        sector = SECTOR_MAP.get(p.symbol.upper(), "其他")
        sector_values[sector] = sector_values.get(sector, 0) + value

    sector_pcts = {s: round(v / total_value, 4) if total_value > 0 else 0 for s, v in sector_values.items()}
    warnings = []
    goals = db.query(UserGoals).first()
    limit = 0.40  # default 40%
    for sector, pct in sector_pcts.items():
        if pct > limit:
            warnings.append({
                "type": "sector_overweight",
                "sector": sector,
                "current_pct": round(pct * 100, 1),
                "limit_pct": round(limit * 100, 1),
                "message": f"{sector}行业占比 {pct*100:.1f}% 超过上限 {limit*100:.0f}%",
            })

    return {"sectors": sector_pcts, "total_value": round(total_value, 2), "warnings": warnings}


def generate_risk_suggestions(db: Session) -> list:
    """
    AI 风控建议：对冲、减仓、现金管理

    Returns list of suggestion dicts, each with: type, title, description, action, details
    """
    risk = compute_portfolio_risk(db)
    exposure = compute_sector_exposure(db)
    goals = db.query(UserGoals).first()
    positions = db.query(Position).filter(Position.is_open == True).all()
    suggestions = []

    # 1. Hedging suggestion when portfolio beta is high
    if positions and risk.get("current_drawdown", 0) > 0.02:
        total_value = exposure.get("total_value", 0)
        hedge_cost = round(total_value * 0.003, 2)  # ~0.3% for a put option
        suggestions.append({
            "type": "hedge",
            "title": "对冲建议",
            "description": f"买入 SPY Put 期权 (30天到期)",
            "cost": f"${hedge_cost}",
            "protection": "大跌时对冲约 60% 的损失",
            "explanation": f"花${hedge_cost}买一份'保险'，市场暴跌时你的损失会小很多。最多亏这${hedge_cost}。",
        })

    # 2. Sector reduction when overweight
    for warning in exposure.get("warnings", []):
        if warning["type"] == "sector_overweight":
            sector = warning["sector"]
            over_pct = warning["current_pct"] - warning["limit_pct"]
            # Find the largest position in this sector to reduce
            sector_map = {"科技": ["AAPL","MSFT","NVDA","GOOGL","META","AMZN"],
                         "金融": ["JPM","BAC","GS","V","MA"],
                         "医疗": ["JNJ","UNH","PFE","ABBV","MRK"],
                         "能源": ["XOM","CVX","COP"]}
            sector_symbols = sector_map.get(sector, [])
            target_pos = None
            for p in positions:
                if p.symbol.upper() in sector_symbols:
                    if target_pos is None or (p.quantity or 0) > (target_pos.quantity or 0):
                        target_pos = p
            if target_pos:
                reduce_shares = max(1, int((target_pos.quantity or 0) * over_pct / 100))
                new_pct = warning["current_pct"] - over_pct
                suggestions.append({
                    "type": "reduce",
                    "title": f"减仓: 卖出 {reduce_shares} 股 {target_pos.symbol}",
                    "description": f"{sector}行业超配 {over_pct:.0f}%。卖出后从 {warning['current_pct']:.0f}% 降至 {new_pct:.0f}%。",
                    "symbol": target_pos.symbol,
                    "shares": reduce_shares,
                    "explanation": "鸡蛋不要放在一个篮子里，分散行业降低风险。",
                })

    # 3. Cash management
    if positions:
        total_value = exposure.get("total_value", 0)
        # Estimate cash ratio (simplified)
        account_value = positions[0].account_balance_at_entry or 100000
        invested = total_value
        cash_ratio = max(0, 1 - invested / account_value) if account_value > 0 else 0
        if cash_ratio < 0.20:
            suggestions.append({
                "type": "cash",
                "title": "保留现金",
                "description": f"当前现金比例约 {cash_ratio*100:.0f}%，建议维持 ≥ 20%",
                "explanation": "留够'子弹'，好机会来了才有钱买。",
            })

    # 4. Drawdown warning
    if risk.get("drawdown_headroom", 1) < 0.03:
        suggestions.append({
            "type": "warning",
            "title": "回撤接近上限",
            "description": f"回撤余量仅 {risk['drawdown_headroom']*100:.1f}%，建议暂停新开仓",
            "explanation": "快到你设定的最大亏损底线了，先稳一稳。",
        })

    return suggestions


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
