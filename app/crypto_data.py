"""
Goal-Driven Trading OS — Crypto Market Data (CCXT)
Works without API keys for public data
"""
import os
import logging
import pandas as pd
from datetime import datetime

logger = logging.getLogger(__name__)


def get_exchange(exchange_name: str = "binance"):
    """获取交易所实例 (公开数据不需要 API key)"""
    try:
        import ccxt
        exchange_cls = getattr(ccxt, exchange_name, None)
        if not exchange_cls:
            return None

        config = {"enableRateLimit": True}
        api_key = os.getenv(f"CCXT_{exchange_name.upper()}_API_KEY")
        secret = os.getenv(f"CCXT_{exchange_name.upper()}_SECRET")
        if api_key and secret:
            config["apiKey"] = api_key
            config["secret"] = secret

        return exchange_cls(config)
    except ImportError:
        logger.error("ccxt not installed")
        return None
    except Exception as e:
        logger.error(f"Exchange init failed: {e}")
        return None


def fetch_crypto_ohlcv(
    symbol: str = "BTC/USDT",
    timeframe: str = "1d",
    exchange_name: str = "binance",
    limit: int = 365,
) -> pd.DataFrame:
    """
    获取加密货币 OHLCV 数据

    Returns DataFrame with: open, high, low, close, volume, returns
    """
    exchange = get_exchange(exchange_name)
    if not exchange:
        return pd.DataFrame()

    try:
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
        df = pd.DataFrame(ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"])
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
        df.set_index("timestamp", inplace=True)
        df["returns"] = df["close"].pct_change()
        return df
    except Exception as e:
        logger.error(f"Crypto OHLCV fetch failed for {symbol}: {e}")
        return pd.DataFrame()


def fetch_crypto_price(symbol: str = "BTC/USDT", exchange_name: str = "binance") -> dict:
    """获取加密货币当前价格"""
    exchange = get_exchange(exchange_name)
    if not exchange:
        return {"symbol": symbol, "price": 0, "error": "Exchange not available"}

    try:
        ticker = exchange.fetch_ticker(symbol)
        return {
            "symbol": symbol,
            "price": round(ticker["last"], 2),
            "change_pct": round(ticker.get("percentage", 0) / 100, 4) if ticker.get("percentage") else 0,
        }
    except Exception as e:
        return {"symbol": symbol, "price": 0, "error": str(e)}


def fetch_batch_crypto_prices(symbols: list[str], exchange_name: str = "binance") -> list[dict]:
    """批量获取加密货币价格"""
    return [fetch_crypto_price(s, exchange_name) for s in symbols]
