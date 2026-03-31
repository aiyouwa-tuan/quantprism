"""
Goal-Driven Trading OS — Broker API (Alpaca)
Graceful degradation: returns None if no API keys configured
"""
import os
import logging

logger = logging.getLogger(__name__)


def get_alpaca_client():
    """
    获取 Alpaca Trading Client
    Returns None if API keys not configured (graceful degradation)
    """
    api_key = os.getenv("ALPACA_API_KEY")
    secret_key = os.getenv("ALPACA_SECRET_KEY")

    if not api_key or not secret_key:
        return None

    try:
        from alpaca.trading.client import TradingClient
        base_url = os.getenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")
        client = TradingClient(api_key, secret_key, paper=True, url_override=base_url)
        return client
    except Exception as e:
        logger.error(f"Alpaca client init failed: {e}")
        return None


def fetch_account_info(client) -> dict:
    """获取账户信息"""
    if not client:
        return {"error": "Broker not connected"}
    try:
        account = client.get_account()
        return {
            "equity": float(account.equity),
            "buying_power": float(account.buying_power),
            "cash": float(account.cash),
            "portfolio_value": float(account.portfolio_value),
            "status": account.status,
        }
    except Exception as e:
        return {"error": str(e)}


def fetch_positions(client) -> list[dict]:
    """获取所有持仓"""
    if not client:
        return []
    try:
        positions = client.get_all_positions()
        return [
            {
                "symbol": p.symbol,
                "qty": float(p.qty),
                "avg_entry_price": float(p.avg_entry_price),
                "current_price": float(p.current_price),
                "market_value": float(p.market_value),
                "unrealized_pl": float(p.unrealized_pl),
                "unrealized_plpc": float(p.unrealized_plpc),
                "side": p.side,
            }
            for p in positions
        ]
    except Exception as e:
        logger.error(f"Fetch positions failed: {e}")
        return []


def submit_order(client, symbol: str, qty: float, side: str,
                 order_type: str = "market", time_in_force: str = "day",
                 limit_price: float = None) -> dict:
    """
    提交订单 (Paper Trading)
    side: "buy" or "sell"
    """
    if not client:
        return {"error": "Broker not connected"}
    try:
        from alpaca.trading.requests import MarketOrderRequest, LimitOrderRequest
        from alpaca.trading.enums import OrderSide, TimeInForce

        side_enum = OrderSide.BUY if side == "buy" else OrderSide.SELL
        tif = TimeInForce.DAY if time_in_force == "day" else TimeInForce.GTC

        if order_type == "limit" and limit_price:
            request = LimitOrderRequest(
                symbol=symbol, qty=qty, side=side_enum,
                time_in_force=tif, limit_price=limit_price,
            )
        else:
            request = MarketOrderRequest(
                symbol=symbol, qty=qty, side=side_enum,
                time_in_force=tif,
            )

        order = client.submit_order(request)
        return {
            "order_id": str(order.id),
            "symbol": order.symbol,
            "qty": str(order.qty),
            "side": str(order.side),
            "status": str(order.status),
            "type": str(order.type),
        }
    except Exception as e:
        return {"error": str(e)}
