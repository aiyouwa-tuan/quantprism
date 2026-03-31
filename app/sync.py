"""
Goal-Driven Trading OS — Position Sync
Syncs broker positions into local database
"""
from datetime import datetime
from sqlalchemy.orm import Session
from models import Position
from broker import get_alpaca_client, fetch_positions


def sync_positions_from_broker(db: Session) -> dict:
    """
    从券商同步持仓到本地数据库

    Returns: {synced, new, closed, error}
    """
    client = get_alpaca_client()
    if not client:
        return {"synced": 0, "new": 0, "closed": 0, "error": "Broker not connected. Set ALPACA_API_KEY and ALPACA_SECRET_KEY environment variables."}

    broker_positions = fetch_positions(client)
    if not broker_positions:
        return {"synced": 0, "new": 0, "closed": 0, "error": None}

    broker_symbols = set()
    new_count = 0
    synced_count = 0

    for bp in broker_positions:
        symbol = bp["symbol"]
        broker_symbols.add(symbol)

        existing = db.query(Position).filter(
            Position.symbol == symbol,
            Position.is_open == True,
            Position.source == "broker",
        ).first()

        if existing:
            existing.current_price = bp["current_price"]
            existing.unrealized_pnl = bp["unrealized_pl"]
            existing.quantity = bp["qty"]
            synced_count += 1
        else:
            risk_per_share = abs(bp["avg_entry_price"] * 0.05)  # default 5% stop estimate
            new_pos = Position(
                symbol=symbol,
                market="stock",
                entry_price=bp["avg_entry_price"],
                stop_loss=bp["avg_entry_price"] - risk_per_share if bp["side"] == "long" else bp["avg_entry_price"] + risk_per_share,
                quantity=bp["qty"],
                source="broker",
                current_price=bp["current_price"],
                unrealized_pnl=bp["unrealized_pl"],
                risk_amount=risk_per_share * bp["qty"],
                risk_pct_of_account=0,  # will be recalculated on dashboard
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
        if pos.symbol not in broker_symbols:
            pos.is_open = False
            pos.close_date = datetime.utcnow()
            closed_count += 1

    db.commit()

    return {
        "synced": synced_count,
        "new": new_count,
        "closed": closed_count,
        "error": None,
    }
