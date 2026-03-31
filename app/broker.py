"""
Goal-Driven Trading OS — Broker API (IBKR via ib_insync)
Graceful degradation: returns None if not connected
"""
import os
import logging

logger = logging.getLogger(__name__)

_ib_client = None


def get_ibkr_client():
    """
    获取 IBKR 连接
    Returns None if ib_insync not installed or TWS/Gateway not running
    """
    global _ib_client
    if _ib_client and _ib_client.isConnected():
        return _ib_client

    try:
        from ib_insync import IB
        host = os.getenv("IBKR_HOST", "127.0.0.1")
        port = int(os.getenv("IBKR_PORT", "7497"))  # 7497=TWS Paper, 7496=TWS Live, 4002=Gateway Paper
        client_id = int(os.getenv("IBKR_CLIENT_ID", "1"))

        ib = IB()
        ib.connect(host, port, clientId=client_id, timeout=5)
        _ib_client = ib
        return ib
    except ImportError:
        logger.info("ib_insync not installed. Run: pip install ib_insync")
        return None
    except Exception as e:
        logger.info(f"IBKR connection failed (TWS/Gateway running?): {e}")
        return None


def fetch_account_info(client=None) -> dict:
    """获取 IBKR 账户信息"""
    if not client:
        client = get_ibkr_client()
    if not client:
        return {"error": "IBKR not connected. Ensure TWS or IB Gateway is running."}
    try:
        account_values = client.accountSummary()
        info = {}
        for av in account_values:
            if av.tag == "NetLiquidation":
                info["equity"] = float(av.value)
            elif av.tag == "BuyingPower":
                info["buying_power"] = float(av.value)
            elif av.tag == "TotalCashValue":
                info["cash"] = float(av.value)
            elif av.tag == "GrossPositionValue":
                info["portfolio_value"] = float(av.value)
        return info
    except Exception as e:
        return {"error": str(e)}


def fetch_positions(client=None) -> list[dict]:
    """获取 IBKR 所有持仓"""
    if not client:
        client = get_ibkr_client()
    if not client:
        return []
    try:
        positions = client.positions()
        return [
            {
                "symbol": p.contract.symbol,
                "qty": float(p.position),
                "avg_entry_price": float(p.avgCost) / 100 if p.contract.secType == "OPT" else float(p.avgCost),
                "current_price": float(p.avgCost),  # will be updated via market data
                "market_value": float(p.position * p.avgCost),
                "unrealized_pl": 0,  # needs market data subscription
                "side": "long" if p.position > 0 else "short",
                "sec_type": p.contract.secType,  # STK, OPT, FUT, etc.
            }
            for p in positions
        ]
    except Exception as e:
        logger.error(f"IBKR fetch positions failed: {e}")
        return []


def submit_order(client=None, symbol: str = "", qty: float = 0, side: str = "buy",
                 order_type: str = "market", limit_price: float = None,
                 sec_type: str = "STK", exchange: str = "SMART",
                 currency: str = "USD") -> dict:
    """
    提交 IBKR 订单

    sec_type: STK (股票), OPT (期权), FUT (期货)
    """
    if not client:
        client = get_ibkr_client()
    if not client:
        return {"error": "IBKR not connected"}
    try:
        from ib_insync import Stock, MarketOrder, LimitOrder

        contract = Stock(symbol, exchange, currency)
        action = "BUY" if side == "buy" else "SELL"

        if order_type == "limit" and limit_price:
            order = LimitOrder(action, qty, limit_price)
        else:
            order = MarketOrder(action, qty)

        trade = client.placeOrder(contract, order)
        return {
            "order_id": str(trade.order.orderId),
            "symbol": symbol,
            "qty": str(qty),
            "side": side,
            "status": str(trade.orderStatus.status),
            "type": order_type,
        }
    except Exception as e:
        return {"error": str(e)}


def disconnect():
    """断开 IBKR 连接"""
    global _ib_client
    if _ib_client and _ib_client.isConnected():
        _ib_client.disconnect()
    _ib_client = None
