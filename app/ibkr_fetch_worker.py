"""
Standalone IBKR data fetcher — runs as subprocess to avoid asyncio conflicts with uvicorn.
Outputs JSON to stdout.

Commands:
  positions  — all positions with real-time P&L
  account    — account summary (equity, buying power, cash)
  portfolio  — positions + account combined (for dashboard)
"""
import json
import sys
import os
import time

sys.path.insert(0, os.path.dirname(__file__))


def main():
    command = sys.argv[1] if len(sys.argv) > 1 else "positions"

    try:
        from ib_insync import IB, Stock, Option

        host = os.getenv("IBKR_HOST", "127.0.0.1")
        port = int(os.getenv("IBKR_PORT", "4001"))
        import random
        client_id = random.randint(100, 999)

        ib = IB()
        ib.connect(host, port, clientId=client_id, timeout=8)

        if command == "positions":
            print(json.dumps(_fetch_positions(ib)))

        elif command == "account":
            print(json.dumps(_fetch_account(ib)))

        elif command == "portfolio":
            # Combined: account + positions with live P&L
            account = _fetch_account(ib)
            positions = _fetch_positions_with_pnl(ib)
            account["positions"] = positions
            account["position_count"] = len(positions)
            print(json.dumps(account))

        ib.disconnect()

    except Exception as e:
        print(json.dumps({"error": str(e)}))
        sys.exit(1)


def _fetch_positions(ib) -> list:
    positions = ib.positions()
    result = []
    for p in positions:
        result.append(_format_position(p))
    return result


def _fetch_positions_with_pnl(ib) -> list:
    """获取持仓 + 实时 PnL"""
    # Request PnL for all positions
    account_id = ib.managedAccounts()[0] if ib.managedAccounts() else ""
    if account_id:
        ib.reqPnL(account_id)
        ib.sleep(1)

    positions = ib.positions()
    result = []

    for p in positions:
        entry = _format_position(p)

        # Try to get real-time price via reqMktData
        try:
            contract = p.contract
            ib.qualifyContracts(contract)
            ticker = ib.reqMktData(contract, "", False, False)
            ib.sleep(0.5)

            if ticker.last and ticker.last > 0:
                current_price = float(ticker.last)
            elif ticker.close and ticker.close > 0:
                current_price = float(ticker.close)
            else:
                current_price = entry["avg_entry_price"]

            entry["current_price"] = round(current_price, 2)

            # Calculate unrealized PnL
            qty = float(p.position)
            avg = float(p.avgCost)
            if p.contract.secType == "OPT":
                # For options, avgCost is total cost per contract
                entry["unrealized_pl"] = round((current_price * 100 - avg) * abs(qty), 2)
            else:
                entry["unrealized_pl"] = round((current_price - avg) * qty, 2)

            ib.cancelMktData(contract)
        except Exception:
            pass

        result.append(entry)

    return result


def _fetch_account(ib) -> dict:
    account_values = ib.accountSummary()
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
        elif av.tag == "UnrealizedPnL":
            info["unrealized_pnl"] = float(av.value)
        elif av.tag == "RealizedPnL":
            info["realized_pnl"] = float(av.value)
    return info


def _format_position(p) -> dict:
    sec_type = p.contract.secType
    qty = float(p.position)
    avg_cost = float(p.avgCost)

    entry = {
        "symbol": p.contract.symbol,
        "qty": abs(qty),
        "avg_entry_price": round(avg_cost, 2),
        "current_price": round(avg_cost, 2),
        "market_value": round(abs(qty) * avg_cost, 2),
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

    return entry


if __name__ == "__main__":
    main()
