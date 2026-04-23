"""QQQ (Nasdaq 100 ETF) 估值 & 技术指标 —— 通过 yfinance 拉取。

当前指标：价格 / RSI-14 / PE / PB / 股息率 / 1年涨幅
历史序列：价格月线 3/5/10Y + 当前价格分位（PE/PB 历史需付费数据源，这里用价格分位代理）
"""
import time
import yfinance as yf
import pandas as pd

_cache: dict = {}
_TTL = 900  # 15 min


def _cached(key, fn):
    entry = _cache.get(key)
    if entry and time.time() - entry["ts"] < _TTL:
        return entry["data"]
    data = fn()
    if not data.get("error"):
        _cache[key] = {"ts": time.time(), "data": data}
    return data


def _rsi(series: pd.Series, period: int = 14) -> float | None:
    """Wilder's RSI from pandas Close series."""
    if len(series) < period + 1:
        return None
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, 1e-10)
    rsi = 100 - (100 / (1 + rs))
    return float(rsi.iloc[-1])


def _percentile(series: pd.Series, value: float) -> float:
    """Current value's percentile rank within series (0-100)."""
    if len(series) == 0:
        return 50.0
    return float((series <= value).mean() * 100)


def fetch_qqq() -> dict:
    def _fetch():
        try:
            tk = yf.Ticker("QQQ")
            info = tk.info or {}

            # 1) 日线 6M 用于 RSI
            daily = tk.history(period="6mo", interval="1d")
            rsi14 = _rsi(daily["Close"]) if not daily.empty else None

            # 2) 月线 10Y 用于历史走势
            monthly = tk.history(period="10y", interval="1mo")
            if monthly.empty:
                return {"error": "no price history"}

            # 结构化数据：时间戳(ms) + 收盘价
            def _to_series(df):
                return [
                    {"date": int(idx.timestamp() * 1000), "close": round(float(row["Close"]), 2)}
                    for idx, row in df.iterrows() if not pd.isna(row["Close"])
                ]

            # 按周期切片
            now = monthly.index[-1]
            hist_3y = monthly[monthly.index >= now - pd.DateOffset(years=3)]
            hist_5y = monthly[monthly.index >= now - pd.DateOffset(years=5)]
            hist_10y = monthly

            current_price = float(monthly["Close"].iloc[-1])

            # 当前价格分位（作为估值分位的代理）
            pct_3y = _percentile(hist_3y["Close"], current_price)
            pct_5y = _percentile(hist_5y["Close"], current_price)
            pct_10y = _percentile(hist_10y["Close"], current_price)

            # 1年涨幅
            one_year_ago = monthly[monthly.index <= now - pd.DateOffset(years=1)]
            yoy_return = None
            if not one_year_ago.empty:
                prev = float(one_year_ago["Close"].iloc[-1])
                yoy_return = round((current_price / prev - 1) * 100, 2)

            # yfinance info 字段（有的可能为 None）
            pe = info.get("trailingPE")
            pb = info.get("priceToBook")
            dividend_yield = info.get("yield")  # ETF 的分红率在 yield 字段
            if dividend_yield is None:
                # 有时在 dividendYield，值是百分比或小数
                dy = info.get("dividendYield")
                if dy is not None:
                    dividend_yield = dy / 100 if dy > 1 else dy

            roe = info.get("returnOnEquity")  # ETF 通常为 None

            return {
                "error": None,
                "fetched_at": int(time.time()),
                "current": {
                    "price": round(current_price, 2),
                    "rsi14": round(rsi14, 1) if rsi14 is not None else None,
                    "pe": round(float(pe), 2) if pe else None,
                    "pb": round(float(pb), 2) if pb else None,
                    "dividend_yield_pct": round(float(dividend_yield) * 100, 2) if dividend_yield else None,
                    "yoy_return_pct": yoy_return,
                    "roe": round(float(roe) * 100, 2) if roe else None,
                },
                "percentile": {
                    "3y": round(pct_3y, 1),
                    "5y": round(pct_5y, 1),
                    "10y": round(pct_10y, 1),
                },
                "history": {
                    "3y": _to_series(hist_3y),
                    "5y": _to_series(hist_5y),
                    "10y": _to_series(hist_10y),
                },
            }
        except Exception as e:
            return {"error": str(e)}

    return _cached("qqq", _fetch)
