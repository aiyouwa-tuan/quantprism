"""
Goal-Driven Trading OS — Broker API (IBKR)
Priority: Web API (Client Portal) → ib_insync (TWS/Gateway) → None
"""
import os
import logging

logger = logging.getLogger(__name__)

_ib_client = None
_connection_mode = None  # "web_api" or "ib_insync" or None


def get_connection_mode() -> str:
    """检测当前连接方式"""
    global _connection_mode
    if _connection_mode:
        return _connection_mode

    # Try Web API first
    try:
        from ibkr_web_api import check_auth_status
        status = check_auth_status()
        if status.get("authenticated"):
            _connection_mode = "web_api"
            return "web_api"
    except Exception:
        pass

    # Try ib_insync
    client = get_ibkr_client()
    if client:
        _connection_mode = "ib_insync"
        return "ib_insync"

    return "disconnected"


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
        port = int(os.getenv("IBKR_PORT", "7496"))  # 7496=TWS Live, 7497=TWS Paper, 4002=Gateway Paper
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
    """获取 IBKR 账户信息 (Web API → ib_insync → error)"""
    # Try Web API first
    try:
        from ibkr_web_api import web_fetch_account
        result = web_fetch_account()
        if "error" not in result:
            return result
    except Exception:
        pass

    # Fall back to ib_insync
    if not client:
        client = get_ibkr_client()
    if not client:
        return {"error": "IBKR 未连接。方案 1: 启动 Client Portal Gateway。方案 2: 打开 TWS/IB Gateway。"}
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
    """获取 IBKR 所有持仓 (Web API → ib_insync → empty)"""
    # Try Web API first
    try:
        from ibkr_web_api import web_fetch_positions
        result = web_fetch_positions()
        if result:
            return result
    except Exception:
        pass

    # Fall back to ib_insync
    if not client:
        client = get_ibkr_client()
    if not client:
        return []
    try:
        positions = client.positions()
        result = []
        for p in positions:
            sec_type = p.contract.secType
            qty = float(p.position)
            avg_cost = float(p.avgCost)

            entry = {
                "symbol": p.contract.symbol,
                "qty": abs(qty),
                "avg_entry_price": avg_cost,
                "current_price": avg_cost,
                "market_value": abs(qty) * avg_cost,
                "unrealized_pl": 0,
                "side": "long" if qty > 0 else "short",
                "sec_type": sec_type,
            }

            if sec_type == "OPT":
                right_label = "Call" if p.contract.right == "C" else "Put"
                entry["market"] = "option"
                entry["right"] = p.contract.right
                entry["strike"] = float(p.contract.strike)
                entry["expiry"] = p.contract.lastTradeDateOrContractMonth
                entry["display_name"] = f"{p.contract.symbol} {right_label} ${p.contract.strike:.0f} {p.contract.lastTradeDateOrContractMonth}"
            else:
                entry["market"] = "stock"
                entry["display_name"] = p.contract.symbol

            result.append(entry)
        return result
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
