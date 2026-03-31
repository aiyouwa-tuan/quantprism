"""
Standalone IBKR data fetcher — runs as subprocess to avoid asyncio conflicts with uvicorn.
Called by sync.py via subprocess.
Outputs JSON to stdout.
"""
import json
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))


def main():
    command = sys.argv[1] if len(sys.argv) > 1 else "positions"

    try:
        from ib_insync import IB

        host = os.getenv("IBKR_HOST", "127.0.0.1")
        port = int(os.getenv("IBKR_PORT", "4001"))
        import random
        client_id = random.randint(100, 999)

        ib = IB()
        ib.connect(host, port, clientId=client_id, timeout=8)

        if command == "positions":
            positions = ib.positions()
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

            print(json.dumps(result))

        elif command == "account":
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
            print(json.dumps(info))

        ib.disconnect()

    except Exception as e:
        print(json.dumps({"error": str(e)}))
        sys.exit(1)


if __name__ == "__main__":
    main()
