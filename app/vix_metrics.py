"""VIX（CBOE 恐慌指数）历史 —— yfinance ^VIX。

关键点：VIX 是脉冲式指数，月线收盘会掩盖日内极值（例如 2025-04-08
盘中 60+，但月末收盘仅 ~25）。所以必须用 **日线** 抓真实高点。

阈值：<12 极度平静 / 12-20 正常 / 20-30 警戒 / >30 恐慌 / >40 极端
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
    if v < 15: return "#4ade80"
    if v < 20: return "#facc15"
    if v < 30: return "#fb923c"
    return "#f87171"


def _vix_label(v: float) -> str:
    if v < 12: return "极度平静"
    if v < 15: return "平静"
    if v < 20: return "正常"
    if v < 30: return "警戒"
    if v < 40: return "恐慌"
    return "极端恐慌"


def _downsample(df: pd.DataFrame, max_points: int = 800) -> pd.DataFrame:
    """如果点数太多就按均匀间隔采样，保留首尾和高低点。"""
    if len(df) <= max_points:
        return df
    step = max(1, len(df) // max_points)
    return df.iloc[::step]


def fetch_vix() -> dict:
    def _fetch():
        try:
            tk = yf.Ticker("^VIX")
            # 拉 max 日线，覆盖所有周期需求
            daily = tk.history(period="max", interval="1d")
            if daily.empty:
                return {"error": "no VIX history"}

            current = float(daily["Close"].iloc[-1])
            today = daily.index[-1]

            # 周期切片（日线）
            slices = {
                "3y": daily[daily.index >= today - pd.DateOffset(years=3)],
                "5y": daily[daily.index >= today - pd.DateOffset(years=5)],
                "10y": daily[daily.index >= today - pd.DateOffset(years=10)],
                "20y": daily[daily.index >= today - pd.DateOffset(years=20)],
            }

            # 统计 — 用日线真实 Close（已包含 2025-04 的 52+ 恐慌）
            stats = {}
            for k, v in slices.items():
                if v.empty:
                    continue
                stats[k] = {
                    "mean": round(float(v["Close"].mean()), 1),
                    "max": round(float(v["Close"].max()), 1),
                    "min": round(float(v["Close"].min()), 1),
                    "percentile": round(float((v["Close"] <= current).mean() * 100), 1),
                    "max_date": v["Close"].idxmax().strftime("%Y-%m-%d"),
                }

            # 历史序列 — 长周期做降采样防性能问题
            def _series(df, max_pts):
                df2 = _downsample(df, max_pts)
                return [
                    {"date": int(idx.timestamp() * 1000), "value": round(float(row["Close"]), 2)}
                    for idx, row in df2.iterrows() if not pd.isna(row["Close"])
                ]

            history = {
                "3y": _series(slices["3y"], 800),
                "5y": _series(slices["5y"], 800),
                "10y": _series(slices["10y"], 800),
                "20y": _series(slices["20y"], 1000),
            }

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
