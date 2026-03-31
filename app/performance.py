"""
Goal-Driven Trading OS — Performance Analytics
组合绩效计算 + 月度收益 + 按策略分解
"""
import numpy as np
import pandas as pd
from datetime import datetime
from sqlalchemy.orm import Session
from models import Position, TradeSignal, ExecutionLog


def compute_portfolio_performance(db: Session) -> dict:
    """
    计算组合整体绩效

    Returns: {total_pnl, win_rate, total_trades, by_strategy, monthly_returns, ...}
    """
    closed = db.query(Position).filter(Position.is_open == False, Position.close_price != None).all()

    if not closed:
        return {
            "total_pnl": 0,
            "total_trades": 0,
            "win_rate": 0,
            "avg_win": 0,
            "avg_loss": 0,
            "profit_factor": 0,
            "by_market": {},
            "monthly_returns": [],
            "equity_curve": [],
        }

    trades = []
    for p in closed:
        pnl = (p.close_price - p.entry_price) * p.quantity
        trades.append({
            "symbol": p.symbol,
            "market": p.market,
            "pnl": round(pnl, 2),
            "entry_date": p.entry_date,
            "close_date": p.close_date,
            "return_pct": round(pnl / (p.entry_price * p.quantity), 4) if p.entry_price and p.quantity else 0,
        })

    wins = [t for t in trades if t["pnl"] > 0]
    losses = [t for t in trades if t["pnl"] <= 0]
    total_pnl = sum(t["pnl"] for t in trades)

    total_wins = sum(t["pnl"] for t in wins)
    total_losses = abs(sum(t["pnl"] for t in losses))
    profit_factor = total_wins / total_losses if total_losses > 0 else float("inf") if total_wins > 0 else 0

    # By market breakdown
    by_market = {}
    for t in trades:
        m = t["market"]
        if m not in by_market:
            by_market[m] = {"count": 0, "pnl": 0, "wins": 0}
        by_market[m]["count"] += 1
        by_market[m]["pnl"] += t["pnl"]
        if t["pnl"] > 0:
            by_market[m]["wins"] += 1

    # Monthly returns
    monthly = {}
    for t in trades:
        if t["close_date"]:
            key = t["close_date"].strftime("%Y-%m")
            monthly[key] = monthly.get(key, 0) + t["pnl"]

    monthly_sorted = [{"month": k, "pnl": round(v, 2)} for k, v in sorted(monthly.items())]

    # Equity curve
    cumulative = 0
    equity = []
    for t in sorted(trades, key=lambda x: x["close_date"] or datetime.min):
        cumulative += t["pnl"]
        equity.append(round(cumulative, 2))

    return {
        "total_pnl": round(total_pnl, 2),
        "total_trades": len(trades),
        "win_rate": round(len(wins) / len(trades), 4) if trades else 0,
        "avg_win": round(np.mean([t["pnl"] for t in wins]), 2) if wins else 0,
        "avg_loss": round(np.mean([t["pnl"] for t in losses]), 2) if losses else 0,
        "profit_factor": round(profit_factor, 2),
        "by_market": by_market,
        "monthly_returns": monthly_sorted,
        "equity_curve": equity,
    }
