"""
Goal-Driven Trading OS — IBKR Client Portal Web API
REST API 接口，不依赖 TWS 图形界面
需要运行 Client Portal Gateway (https://www.interactivebrokers.com/en/trading/ib-api.php)

启动方式：
1. 下载 Client Portal Gateway: https://download2.interactivebrokers.com/portal/clientportal.gw.zip
2. 解压后运行: cd clientportal.gw && bin/run.sh root/conf.yaml
3. 浏览器打开 https://localhost:5000 登录一次
4. 之后本程序可以直接调用 REST API
"""
import os
import logging
import json
from typing import Optional

logger = logging.getLogger(__name__)

BASE_URL = os.getenv("IBKR_WEB_API_URL", "https://localhost:5000/v1/api")
# Client Portal Gateway 使用自签名证书，需要跳过验证
VERIFY_SSL = False


def _request(method: str, path: str, data: dict = None) -> dict:
    """发起 IBKR Web API 请求"""
    try:
        import httpx
        url = f"{BASE_URL}{path}"
        with httpx.Client(verify=VERIFY_SSL, timeout=10) as client:
            if method == "GET":
                resp = client.get(url)
            elif method == "POST":
                resp = client.post(url, json=data)
            else:
                return {"error": f"Unsupported method: {method}"}

            if resp.status_code == 200:
                return resp.json() if resp.text else {}
            elif resp.status_code == 401:
                return {"error": "未认证。请先在浏览器打开 https://localhost:5000 登录。"}
            else:
                return {"error": f"HTTP {resp.status_code}: {resp.text[:200]}"}
    except ImportError:
        return {"error": "httpx 未安装。运行 pip install httpx"}
    except Exception as e:
        err = str(e)
        if "Connection refused" in err:
            return {"error": "Client Portal Gateway 未运行。请先启动: cd clientportal.gw && bin/run.sh root/conf.yaml"}
        return {"error": err}


def check_auth_status() -> dict:
    """检查认证状态"""
    result = _request("POST", "/iserver/auth/status")
    if "error" in result:
        return result
    authenticated = result.get("authenticated", False)
    return {
        "authenticated": authenticated,
        "competing": result.get("competing", False),
        "message": result.get("message", ""),
    }


def web_fetch_account() -> dict:
    """获取账户信息"""
    # First get account IDs
    accounts = _request("GET", "/iserver/accounts")
    if "error" in accounts:
        return accounts

    account_ids = accounts.get("accounts", [])
    if not account_ids:
        return {"error": "No accounts found"}

    account_id = account_ids[0]
    # Get account summary
    summary = _request("GET", f"/portfolio/{account_id}/summary")
    if "error" in summary:
        return summary

    return {
        "account_id": account_id,
        "equity": float(summary.get("netliquidation", {}).get("amount", 0)),
        "buying_power": float(summary.get("buyingpower", {}).get("amount", 0)),
        "cash": float(summary.get("totalcashvalue", {}).get("amount", 0)),
    }


def web_fetch_positions() -> list[dict]:
    """获取所有持仓"""
    # Get account ID first
    accounts = _request("GET", "/iserver/accounts")
    if "error" in accounts:
        return []

    account_ids = accounts.get("accounts", [])
    if not account_ids:
        return []

    account_id = account_ids[0]
    positions = _request("GET", f"/portfolio/{account_id}/positions/0")
    if "error" in positions or not isinstance(positions, list):
        return []

    result = []
    for p in positions:
        sec_type = p.get("assetClass", "STK")
        symbol = p.get("contractDesc", p.get("ticker", ""))
        qty = float(p.get("position", 0))
        avg_cost = float(p.get("avgCost", 0))
        mkt_value = float(p.get("mktValue", 0))
        unrealized = float(p.get("unrealizedPnl", 0))
        current_price = float(p.get("mktPrice", avg_cost))

        entry = {
            "symbol": p.get("ticker", symbol),
            "qty": abs(qty),
            "avg_entry_price": avg_cost,
            "current_price": current_price,
            "market_value": mkt_value,
            "unrealized_pl": unrealized,
            "side": "long" if qty > 0 else "short",
            "sec_type": sec_type,
            "conid": p.get("conid"),
        }

        if sec_type == "OPT":
            entry["market"] = "option"
            entry["display_name"] = p.get("contractDesc", symbol)
        else:
            entry["market"] = "stock"
            entry["display_name"] = p.get("ticker", symbol)

        result.append(entry)

    return result


def web_fetch_market_data(conids: list[int]) -> dict:
    """获取实时行情（通过 conid）"""
    if not conids:
        return {}

    conid_str = ",".join(str(c) for c in conids)
    result = _request("GET", f"/iserver/marketdata/snapshot?conids={conid_str}&fields=31,84,86")
    if "error" in result or not isinstance(result, list):
        return {}

    data = {}
    for item in result:
        conid = item.get("conid")
        data[conid] = {
            "last_price": item.get("31", 0),
            "bid": item.get("84", 0),
            "ask": item.get("86", 0),
        }
    return data


def web_search_contract(symbol: str, sec_type: str = "STK") -> Optional[int]:
    """搜索合约获取 conid"""
    result = _request("GET", f"/iserver/secdef/search?symbol={symbol}&secType={sec_type}")
    if "error" in result or not isinstance(result, list) or len(result) == 0:
        return None
    return result[0].get("conid")


def web_fetch_option_chain(conid: int, month: str = None) -> list[dict]:
    """获取期权链"""
    # Get available strikes
    info = _request("GET", f"/iserver/secdef/info?conid={conid}&secType=OPT")
    if "error" in info:
        return []

    # Get strikes for the target month
    params = f"conid={conid}&sectype=OPT"
    if month:
        params += f"&month={month}"

    strikes = _request("GET", f"/iserver/secdef/strikes?{params}")
    if "error" in strikes:
        return []

    return strikes.get("put", []) + strikes.get("call", [])
