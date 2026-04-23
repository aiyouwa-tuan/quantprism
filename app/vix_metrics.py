"""VIX（恐慌指数）历史 —— 通过 yfinance ^VIX。

3/5/10/20 年月线。关键阈值：<12 极度平静 / 20 警戒 / 30 恐慌 / 40+ 极端。
"""
import time
import yfinance as yf
import pandas as pd

_cache: dict = {}
_TTL = 900


def _cached(key, fn):
    entry = _cache.get(key)
    if entry and time.time() - entry["ts"] < _TTL:
        return entry["data"]
    data = fn()
    if not data.get("error"):
        _cache[key] = {"ts": time.time(), "data": data}
    return data


def _vix_color(v: float) -> str:
    if v < 15: return "#4ade80"   # 平静
    if v < 20: return "#facc15"   # 正常
    if v < 30: return "#fb923c"   # 警戒
    return "#f87171"              # 恐慌


def _vix_label(v: float) -> str:
    if v < 12: return "极度平静"
    if v < 15: return "平静"
    if v < 20: return "正常"
    if v < 30: return "警戒"
    if v < 40: return "恐慌"
    return "极端恐慌"


def fetch_vix() -> dict:
    def _fetch():
        try:
            tk = yf.Ticker("^VIX")
            monthly = tk.history(period="max", interval="1mo")
            if monthly.empty:
                return {"error": "no VIX history"}

            # 日线取当前值（更及时）
            daily = tk.history(period="5d", interval="1d")
            current = float(daily["Close"].iloc[-1]) if not daily.empty else float(monthly["Close"].iloc[-1])

            def _series(df):
                return [
                    {"date": int(idx.timestamp() * 1000), "value": round(float(row["Close"]), 2)}
                    for idx, row in df.iterrows() if not pd.isna(row["Close"])
                ]

            now = monthly.index[-1]
            slices = {
                "3y": monthly[monthly.index >= now - pd.DateOffset(years=3)],
                "5y": monthly[monthly.index >= now - pd.DateOffset(years=5)],
                "10y": monthly[monthly.index >= now - pd.DateOffset(years=10)],
                "20y": monthly[monthly.index >= now - pd.DateOffset(years=20)],
            }

            stats = {}
            for k, v in slices.items():
                if v.empty:
                    continue
                stats[k] = {
                    "mean": round(float(v["Close"].mean()), 1),
                    "max": round(float(v["Close"].max()), 1),
                    "min": round(float(v["Close"].min()), 1),
                    "percentile": round(float((v["Close"] <= current).mean() * 100), 1),
                }

            history = {k: _series(v) for k, v in slices.items()}

            return {
                "error": None,
                "current": {
                    "value": round(current, 2),
                    "color": _vix_color(current),
                    "label": _vix_label(current),
                },
                "stats": stats,
                "history": history,
            }
        except Exception as e:
            return {"error": str(e)}

    return _cached("vix", _fetch)
