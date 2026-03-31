"""
Goal-Driven Trading OS — Position Sync
Syncs broker positions into local database with real-time P&L
"""
from datetime import datetime
from sqlalchemy.orm import Session
from models import Position
from broker import fetch_positions, fetch_portfolio


def sync_positions_from_broker(db: Session, with_pnl: bool = False) -> dict:
    """
    从 IBKR 同步持仓到本地数据库

    Args:
        with_pnl: True = 获取实时价格和 P&L（慢 10-15s），False = 只获取持仓（快 3s）
    """
    if with_pnl:
        portfolio = fetch_portfolio()
        broker_positions = portfolio.get("positions", [])
        account_info = {k: v for k, v in portfolio.items() if k != "positions"}
        if not broker_positions and "error" in portfolio:
            return {"synced": 0, "new": 0, "closed": 0, "error": portfolio["error"], "account": {}}
    else:
        broker_positions = fetch_positions()
        account_info = {}

    if not broker_positions:
        return {"synced": 0, "new": 0, "closed": 0, "error": None, "account": account_info}

    broker_keys = set()
    new_count = 0
    synced_count = 0

    for bp in broker_positions:
        display_name = bp.get("display_name", bp["symbol"])
        broker_keys.add(display_name)
        market = bp.get("market", "stock")

        existing = db.query(Position).filter(
            Position.symbol == display_name,
            Position.is_open == True,
            Position.source == "broker",
        ).first()

        if existing:
            existing.current_price = bp.get("current_price", existing.current_price)
            existing.unrealized_pnl = bp.get("unrealized_pl", 0)
            existing.quantity = bp["qty"]
            synced_count += 1
        else:
            entry_price = bp["avg_entry_price"]
            risk_est = abs(entry_price * 0.05)
            new_pos = Position(
                symbol=display_name,
                market=market,
                entry_price=entry_price,
                stop_loss=entry_price - risk_est if bp["side"] == "long" else entry_price + risk_est,
                quantity=bp["qty"],
                source="broker",
                current_price=bp.get("current_price", entry_price),
                unrealized_pnl=bp.get("unrealized_pl", 0),
                risk_amount=risk_est * bp["qty"],
                risk_pct_of_account=0,
                account_balance_at_entry=0,
            )
            db.add(new_pos)
            new_count += 1

    # Close positions no longer in broker
    closed_count = 0
    open_broker_positions = db.query(Position).filter(
        Position.is_open == True,
        Position.source == "broker",
    ).all()
    for pos in open_broker_positions:
        if pos.symbol not in broker_keys:
            pos.is_open = False
            pos.close_date = datetime.utcnow()
            closed_count += 1

    db.commit()

    return {
        "synced": synced_count,
        "new": new_count,
        "closed": closed_count,
        "total": len(broker_positions),
        "account": account_info,
        "error": None,
    }
