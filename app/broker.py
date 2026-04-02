"""
Goal-Driven Trading OS — Broker API (IBKR) v2
支持：读取持仓 + Paper Trading 下单 + 订单状态跟踪

连接优先级: Web API → subprocess worker → disconnected
"""
import os
import sys
import json
import logging
import subprocess
from pathlib import Path
from datetime import datetime

logger = logging.getLogger(__name__)

APP_DIR = Path(__file__).resolve().parent
PYTHON = sys.executable
WORKER = str(APP_DIR / "ibkr_fetch_worker.py")


def _run_worker(command: str, timeout: int = 15) -> dict:
    """通过子进程调用 IBKR worker（避免 asyncio 冲突）"""
    try:
        result = subprocess.run(
            [PYTHON, WORKER, command],
            capture_output=True, text=True, timeout=timeout,
            cwd=str(APP_DIR),
        )
        if result.returncode == 0 and result.stdout.strip():
            return json.loads(result.stdout.strip())
        else:
            stderr = result.stderr.strip()[:200] if result.stderr else ""
            return {"error": f"Worker failed: {stderr}"}
    except subprocess.TimeoutExpired:
        return {"error": "IBKR 连接超时。请确保 TWS 或 IB Gateway 正在运行。"}
    except Exception as e:
        return {"error": str(e)}


def get_connection_mode() -> str:
    """检测当前连接方式"""
    try:
        from ibkr_web_api import check_auth_status
        status = check_auth_status()
        if status.get("authenticated"):
            return "web_api"
    except Exception:
        pass

    result = _run_worker("account", timeout=12)
    if isinstance(result, dict) and "error" not in result:
        return "ib_insync"

    return "disconnected"


def fetch_account_info() -> dict:
    """获取 IBKR 账户信息"""
    try:
        from ibkr_web_api import web_fetch_account
        result = web_fetch_account()
        if "error" not in result:
            return result
    except Exception:
        pass

    result = _run_worker("account")
    if isinstance(result, dict):
        return result
    return {"error": "IBKR 未连接"}


def fetch_positions() -> list:
    """获取 IBKR 所有持仓"""
    try:
        from ibkr_web_api import web_fetch_positions
        result = web_fetch_positions()
        if result:
            return result
    except Exception:
        pass

    result = _run_worker("positions")
    if isinstance(result, list):
        return result
    return []


def fetch_portfolio() -> dict:
    """获取完整组合数据"""
    result = _run_worker("portfolio", timeout=30)
    if isinstance(result, dict) and "error" not in result:
        return result
    return {
        "error": result.get("error", "IBKR 未连接") if isinstance(result, dict) else "IBKR 未连接",
        "positions": [], "position_count": 0,
    }


# ========== Paper Trading 订单系统 ==========

_paper_orders: list = []
_next_order_id = 1000


def submit_order(symbol: str = "", qty: float = 0, side: str = "buy",
                 order_type: str = "market", limit_price: float = None,
                 paper: bool = True) -> dict:
    """
    提交订单
    paper=True: 模拟成交（Paper Trading）
    paper=False: 通过 IBKR 真实下单
    """
    global _next_order_id

    if not symbol or qty <= 0:
        return {"error": "请提供有效的标的代码和数量"}

    if paper:
        from market_data import fetch_current_price
        price_data = fetch_current_price(symbol)
        fill_price = price_data.get("price", 0)
        if fill_price <= 0:
            return {"error": f"无法获取 {symbol} 的实时价格"}

        if order_type == "limit" and limit_price:
            if side == "buy" and limit_price < fill_price:
                fill_price = limit_price
            elif side == "sell" and limit_price > fill_price:
                fill_price = limit_price

        order_id = f"PAPER-{_next_order_id}"
        _next_order_id += 1

        order = {
            "order_id": order_id,
            "symbol": symbol.upper(),
            "side": side,
            "quantity": qty,
            "order_type": order_type,
            "limit_price": limit_price,
            "fill_price": round(fill_price, 2),
            "status": "filled",
            "filled_at": datetime.utcnow().isoformat(),
            "paper": True,
            "commission": round(max(qty * 0.005, 1.0), 2),
        }
        _paper_orders.append(order)
        logger.info(f"[Paper] {side.upper()} {qty} {symbol} @ ${fill_price:.2f}")
        return order

    else:
        mode = get_connection_mode()
        if mode == "disconnected":
            return {"error": "IBKR 未连接。请确保 TWS 正在运行。"}
        return {"error": "真实下单需要在 TWS 中取消 'Read-Only API'"}


def get_paper_orders() -> list:
    """获取所有 Paper Trading 订单"""
    return list(reversed(_paper_orders))


def get_order_status(order_id: str) -> dict:
    """查询订单状态"""
    for order in _paper_orders:
        if order["order_id"] == order_id:
            return order
    return {"error": f"订单 {order_id} 不存在"}


def disconnect():
    pass
