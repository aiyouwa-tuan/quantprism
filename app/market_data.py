"""
Goal-Driven Trading OS — Market Data Layer
yfinance for stocks, ta for technical indicators
"""
import os
import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime, timedelta
from ta.momentum import RSIIndicator
from ta.volatility import BollingerBands, AverageTrueRange
from ta.trend import SMAIndicator


# In-memory cache: {symbol_period: (timestamp, dataframe)}
_cache: dict = {}
_CACHE_TTL = 3600  # 1 hour


def fetch_stock_history(
    symbol: str,
    start: str = None,
    end: str = None,
    interval: str = "1d",
    period: str = "2y",
) -> pd.DataFrame:
    """
    获取股票历史数据（带 1 小时内存缓存）

    Returns DataFrame with columns: open, high, low, close, volume, returns
    """
    cache_key = f"{symbol}_{start}_{end}_{period}"
    now = datetime.now().timestamp()

    # Check cache
    if cache_key in _cache:
        cached_time, cached_df = _cache[cache_key]
        if now - cached_time < _CACHE_TTL:
            return cached_df.copy()

    ticker = yf.Ticker(symbol)
    if start and end:
        df = ticker.history(start=start, end=end, interval=interval, auto_adjust=True)
    else:
        df = ticker.history(period=period, interval=interval, auto_adjust=True)

    if df.empty:
        return df

    df.columns = [c.lower() for c in df.columns]
    df = df[["open", "high", "low", "close", "volume"]].copy()
    df["returns"] = df["close"].pct_change()

    # Store in cache
    _cache[cache_key] = (now, df.copy())

    return df


def fetch_current_price(symbol: str) -> dict:
    """获取当前价格"""
    try:
        ticker = yf.Ticker(symbol)
        info = ticker.fast_info
        try:
            price = info.last_price
            prev = info.previous_close
            change_pct = (price - prev) / prev if prev else 0
        except Exception:
            hist = ticker.history(period="2d")
            if hist.empty:
                return {"symbol": symbol.upper(), "price": 0, "change_pct": 0, "error": "no data"}
            price = hist["Close"].iloc[-1]
            prev = hist["Close"].iloc[-2] if len(hist) > 1 else price
            change_pct = (price - prev) / prev if prev else 0
    except Exception:
        return {"symbol": symbol.upper(), "price": 0, "change_pct": 0, "error": "unavailable"}

    return {
        "symbol": symbol.upper(),
        "price": round(float(price), 2),
        "change_pct": round(float(change_pct), 4),
    }


def fetch_vix() -> dict:
    """获取 VIX 指数"""
    return fetch_current_price("^VIX")


def fetch_batch_prices(symbols: list[str]) -> list[dict]:
    """批量获取价格"""
    return [fetch_current_price(s) for s in symbols]


def compute_technicals(df: pd.DataFrame) -> pd.DataFrame:
    """
    计算技术指标: SMA, RSI, Bollinger Bands, ATR

    Input: DataFrame with open, high, low, close columns
    Output: 同一 DataFrame 添加指标列
    """
    if df.empty or len(df) < 20:
        return df

    close = df["close"]

    # SMA
    df["sma_20"] = SMAIndicator(close, window=20).sma_indicator()
    df["sma_50"] = SMAIndicator(close, window=50).sma_indicator()
    df["sma_200"] = SMAIndicator(close, window=200).sma_indicator()

    # RSI
    df["rsi_14"] = RSIIndicator(close, window=14).rsi()

    # Bollinger Bands
    bb = BollingerBands(close, window=20, window_dev=2)
    df["bb_upper"] = bb.bollinger_hband()
    df["bb_lower"] = bb.bollinger_lband()
    df["bb_mid"] = bb.bollinger_mavg()

    # ATR
    atr = AverageTrueRange(df["high"], df["low"], close, window=14)
    df["atr_14"] = atr.average_true_range()

    return df


def detect_market_regime(vix_value: float = None) -> dict:
    """
    基于 VIX 检测市场环境

    Returns: {regime, vix, description}
    """
    if vix_value is None:
        vix_data = fetch_vix()
        vix_value = vix_data.get("price", 20)

    if vix_value < 15:
        regime = "low_vol"
        desc = "低波动 (平静市场)"
    elif vix_value < 20:
        regime = "normal"
        desc = "正常波动"
    elif vix_value < 30:
        regime = "mid_vol"
        desc = "中等波动 (谨慎)"
    else:
        regime = "high_vol"
        desc = "高波动 (危险)"

    return {
        "regime": regime,
        "vix": round(vix_value, 2),
        "description": desc,
    }
