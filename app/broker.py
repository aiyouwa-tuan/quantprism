"""
Goal-Driven Trading OS — Broker API (IBKR)
Priority: Web API → subprocess worker (避免 asyncio 冲突) → None

ib_insync 和 uvicorn 都用 asyncio，直接调用会冲突。
解决方案：用 subprocess 调用 ibkr_fetch_worker.py 获取数据。
"""
import os
import sys
import json
import logging
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

APP_DIR = Path(__file__).resolve().parent
PYTHON = sys.executable  # 当前 Python 解释器路径
WORKER = str(APP_DIR / "ibkr_fetch_worker.py")


def _run_worker(command: str, timeout: int = 15) -> dict | list:
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
    # Try Web API first
    try:
        from ibkr_web_api import check_auth_status
        status = check_auth_status()
        if status.get("authenticated"):
            return "web_api"
    except Exception:
        pass

    # Try ib_insync via worker
    result = _run_worker("account", timeout=12)
    if isinstance(result, dict) and "error" not in result:
        return "ib_insync"

    return "disconnected"


def fetch_account_info() -> dict:
    """获取 IBKR 账户信息"""
    # Try Web API first
    try:
        from ibkr_web_api import web_fetch_account
        result = web_fetch_account()
        if "error" not in result:
            return result
    except Exception:
        pass

    # Fall back to subprocess worker
    result = _run_worker("account")
    if isinstance(result, dict):
        return result
    return {"error": "IBKR 未连接"}


def fetch_positions() -> list[dict]:
    """获取 IBKR 所有持仓"""
    # Try Web API first
    try:
        from ibkr_web_api import web_fetch_positions
        result = web_fetch_positions()
        if result:
            return result
    except Exception:
        pass

    # Fall back to subprocess worker
    result = _run_worker("positions")
    if isinstance(result, list):
        return result
    return []


def submit_order(symbol: str = "", qty: float = 0, side: str = "buy",
                 order_type: str = "market", limit_price: float = None) -> dict:
    """提交 IBKR 订单 (暂时只支持读取模式)"""
    return {"error": "当前为只读模式。需要在 TWS 中取消勾选 'Read-Only API' 才能下单。"}


def disconnect():
    """断开 IBKR 连接（worker 模式无需断开）"""
    pass
