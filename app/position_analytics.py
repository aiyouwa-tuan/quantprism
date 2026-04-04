"""
QuantPrism — Enhanced Position Analytics
Hero BNV, Delta/Theta exposure, support levels, portfolio segmentation
"""
import numpy as np


def compute_position_analytics(positions: list, account_info: dict = None) -> dict:
    """
    Compute enhanced position analytics for the positions page.

    Returns:
        hero_bnv: total book net value
        daily_change: today's P&L change
        daily_change_pct: today's P&L change %
        is_realtime: whether data is from IBKR real-time
        options: filtered option positions
        stocks: filtered stock positions
        option_count / stock_count
        total_delta: net delta exposure
        total_theta: net theta decay
    """
    if not positions:
        return {
            "hero_bnv": 0,
            "daily_change": 0,
            "daily_change_pct": 0,
            "is_realtime": False,
            "options": [],
            "stocks": [],
            "option_count": 0,
            "stock_count": 0,
            "total_delta": 0,
            "total_theta": 0,
            "scroll_strip": [],
        }

    # Segment by type
    options = [p for p in positions if getattr(p, 'market', 'stock') == 'option']
    stocks = [p for p in positions if getattr(p, 'market', 'stock') != 'option']

    # Hero BNV calculation
    total_equity = 0
    total_unrealized = 0
    scroll_strip = []

    for p in positions:
        current = getattr(p, 'current_price', None) or getattr(p, 'entry_price', 0)
        entry = getattr(p, 'entry_price', 0)
        qty = getattr(p, 'quantity', 0)

        market_value = current * qty
        total_equity += market_value

        unrealized = getattr(p, 'unrealized_pnl', None) or ((current - entry) * qty)
        total_unrealized += unrealized

        scroll_strip.append({
            "symbol": getattr(p, 'symbol', '???'),
            "pnl": round(unrealized, 2),
            "market": getattr(p, 'market', 'stock'),
            "risk_pct": getattr(p, 'risk_pct_of_account', 0) or 0,
        })

    # Account info overrides
    if account_info:
        hero_bnv = account_info.get("net_equity", total_equity) or total_equity
        is_realtime = account_info.get("connected", False)
    else:
        hero_bnv = total_equity
        is_realtime = False

    # Delta/Theta aggregation (placeholder — real values from IBKR Greeks)
    total_delta = 0
    total_theta = 0
    for p in options:
        delta = getattr(p, 'delta', None) or 0
        theta = getattr(p, 'theta', None) or 0
        qty = getattr(p, 'quantity', 0)
        total_delta += delta * qty
        total_theta += theta * qty

    daily_change_pct = (total_unrealized / hero_bnv * 100) if hero_bnv else 0

    return {
        "hero_bnv": round(hero_bnv, 2),
        "daily_change": round(total_unrealized, 2),
        "daily_change_pct": round(daily_change_pct, 2),
        "is_realtime": is_realtime,
        "options": options,
        "stocks": stocks,
        "option_count": len(options),
        "stock_count": len(stocks),
        "total_delta": round(total_delta, 2),
        "total_theta": round(total_theta, 2),
        "scroll_strip": sorted(scroll_strip, key=lambda x: abs(x["pnl"]), reverse=True),
    }
