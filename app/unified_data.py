"""
Goal-Driven Trading OS — Unified Data Layer
Routes to correct data source based on market type
"""
from market_data import fetch_stock_history, fetch_current_price
from crypto_data import fetch_crypto_ohlcv, fetch_crypto_price
from options_data import fetch_options_chain


def fetch_history(symbol: str, market: str, start: str = None, end: str = None, period: str = "2y"):
    """统一历史数据获取"""
    if market == "crypto":
        return fetch_crypto_ohlcv(symbol)
    elif market == "option":
        return fetch_stock_history(symbol.split(" ")[0], start=start, end=end, period=period)
    else:
        return fetch_stock_history(symbol, start=start, end=end, period=period)


def fetch_price(symbol: str, market: str) -> dict:
    """统一当前价格获取"""
    if market == "crypto":
        return fetch_crypto_price(symbol)
    else:
        return fetch_current_price(symbol)


def fetch_batch_prices(positions) -> dict:
    """批量获取价格，按市场类型分组"""
    results = {}
    for p in positions:
        key = f"{p.symbol}_{p.market}"
        if key not in results:
            results[key] = fetch_price(p.symbol, p.market)
    return results
