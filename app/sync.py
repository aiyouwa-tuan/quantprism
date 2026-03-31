"""
Goal-Driven Trading OS — Position Sync
Syncs broker positions into local database (supports stocks + options)
"""
from datetime import datetime
from sqlalchemy.orm import Session
from models import Position
from broker import get_ibkr_client, fetch_positions


def sync_positions_from_broker(db: Session) -> dict:
    """
    从 IBKR 同步持仓到本地数据库

    Returns: {synced, new, closed, error, details}
    """
    client = get_ibkr_client()
    if not client:
        return {"synced": 0, "new": 0, "closed": 0, "error": "IBKR 未连接。请确保 TWS 或 IB Gateway 正在运行。"}

    broker_positions = fetch_positions(client)
    if not broker_positions:
        return {"synced": 0, "new": 0, "closed": 0, "error": None}

    # Use display_name as unique key (handles same symbol with different options)
    broker_keys = set()
    new_count = 0
    synced_count = 0

    for bp in broker_positions:
        display_name = bp.get("display_name", bp["symbol"])
        broker_keys.add(display_name)

        # Match by symbol + source=broker. For options, match by display_name in notes field
        existing = db.query(Position).filter(
            Position.symbol == display_name,
            Position.is_open == True,
            Position.source == "broker",
        ).first()

        market = bp.get("market", "stock")

        if existing:
            existing.current_price = bp["current_price"]
            existing.unrealized_pnl = bp["unrealized_pl"]
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
                current_price=bp["current_price"],
                unrealized_pnl=bp["unrealized_pl"],
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
        "error": None,
    }
