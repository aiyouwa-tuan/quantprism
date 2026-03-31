"""
Goal-Driven Trading OS — Execution Engine
信号生成 → 人工确认 → 执行
"""
import yaml
from datetime import datetime, timedelta
from sqlalchemy.orm import Session

from models import TradeSignal, StrategyConfig, Position, ExecutionLog, UserGoals
from strategies.base import get_strategy
from market_data import fetch_stock_history, compute_technicals, fetch_current_price
from calculator import calculate_position_size
from broker import get_alpaca_client, submit_order


def generate_pending_signals(db: Session) -> int:
    """
    对所有活跃策略生成待确认信号

    Returns: 生成的信号数量
    """
    active_configs = db.query(StrategyConfig).filter(StrategyConfig.is_active == True).all()
    goals = db.query(UserGoals).first()
    count = 0

    for config in active_configs:
        strategy_cls = get_strategy(config.strategy_name)
        if not strategy_cls:
            continue

        params = yaml.safe_load(config.params_yaml) if config.params_yaml else {}
        strategy = strategy_cls(params)

        df = fetch_stock_history(config.symbol, period="6mo")
        if df.empty:
            continue

        df = compute_technicals(df)
        signals = strategy.generate_signals(df)

        if not signals:
            continue

        # 只取最新的信号
        latest = signals[-1]
        price_data = fetch_current_price(config.symbol)
        current_price = price_data.get("price", latest.entry_price)

        # 计算仓位
        risk_per_trade = goals.risk_per_trade if goals else 0.02
        account_balance = 10000  # TODO: get from broker or user input

        signal_qty = 0
        if latest.stop_loss and latest.stop_loss != current_price:
            risk_per_share = abs(current_price - latest.stop_loss)
            if risk_per_share > 0:
                signal_qty = int((account_balance * risk_per_trade) / risk_per_share)

        signal = TradeSignal(
            strategy_config_id=config.id,
            symbol=config.symbol,
            direction=latest.direction,
            signal_price=current_price,
            signal_stop_loss=latest.stop_loss,
            signal_quantity=max(signal_qty, 1),
            confidence=latest.confidence,
            status="pending",
        )
        db.add(signal)
        count += 1

    db.commit()
    return count


def execute_confirmed_signal(signal_id: int, db: Session) -> dict:
    """
    执行已确认的信号

    Returns: {success, message, order}
    """
    signal = db.query(TradeSignal).filter(TradeSignal.id == signal_id).first()
    if not signal:
        return {"success": False, "message": "Signal not found"}

    if signal.status != "confirmed":
        return {"success": False, "message": f"Signal status is '{signal.status}', must be 'confirmed'"}

    client = get_alpaca_client()

    # Record execution log
    log = ExecutionLog(
        signal_id=signal.id,
        symbol=signal.symbol,
        side="buy" if signal.direction == "long" else "sell",
        order_type="market",
        requested_qty=signal.signal_quantity,
        requested_price=signal.signal_price,
    )

    if client:
        side = "buy" if signal.direction == "long" else "sell"
        order = submit_order(client, signal.symbol, signal.signal_quantity, side)

        if "error" in order:
            log.status = "rejected"
            log.error_message = order["error"]
            signal.status = "skipped"
            signal.deviation_reason = f"Broker error: {order['error']}"
        else:
            log.broker_order_id = order.get("order_id")
            log.status = "filled"
            log.filled_qty = signal.signal_quantity
            log.filled_price = signal.signal_price
            log.filled_at = datetime.utcnow()
            signal.status = "executed"
            signal.execution_price = signal.signal_price
            signal.execution_quantity = signal.signal_quantity
            signal.execution_time = datetime.utcnow()
    else:
        # No broker: mark as executed (manual trading mode)
        log.status = "filled"
        log.filled_qty = signal.signal_quantity
        log.filled_price = signal.signal_price
        log.filled_at = datetime.utcnow()
        signal.status = "executed"
        signal.execution_price = signal.signal_price
        signal.execution_quantity = signal.signal_quantity
        signal.execution_time = datetime.utcnow()

    db.add(log)
    db.commit()

    return {"success": True, "message": "Signal executed", "signal": signal}


def expire_stale_signals(db: Session, max_age_minutes: int = 60) -> int:
    """过期超时的未确认信号"""
    cutoff = datetime.utcnow() - timedelta(minutes=max_age_minutes)
    stale = db.query(TradeSignal).filter(
        TradeSignal.status == "pending",
        TradeSignal.signal_time < cutoff,
    ).all()

    for s in stale:
        s.status = "expired"

    db.commit()
    return len(stale)
