"""VIX（CBOE 恐慌指数）历史 —— 长桥 OpenAPI 为主源，yfinance 做 fallback。

长桥代码 `.VIX.US` 返回真实 CBOE VIX 日线 OHLC，覆盖 2005-至今 21+ 年。
yfinance `^VIX` 作为备用（长桥未初始化时用）。

阈值：<12 极度平静 / 12-20 正常 / 20-30 警戒 / >30 恐慌 / >40 极端
"""
import time
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


def _downsample(bars: list, max_points: int) -> list:
    if len(bars) <= max_points:
        return bars
    step = max(1, len(bars) // max_points)
    return bars[::step]


def _load_bars() -> tuple[list, str]:
    """拉 VIX 日线，优先长桥；失败回落 yfinance。返回 (bars, source)。

    bars 格式：[{date: ms_ts, close, high, low, open}, ...] 升序
    """
    # 主源：长桥
    try:
        from longport_client import fetch_vix_history
        d = fetch_vix_history()
        if not d.get("error") and d.get("bars"):
            return d["bars"], "长桥 OpenAPI (.VIX.US)"
    except Exception:
        pass

    # 备源：yfinance
    import yfinance as yf
    tk = yf.Ticker("^VIX")
    daily = tk.history(period="max", interval="1d")
    bars = []
    for idx, row in daily.iterrows():
        if pd.isna(row["Close"]):
            continue
        bars.append({
            "date": int(idx.timestamp() * 1000),
            "open": float(row["Open"]),
            "high": float(row["High"]),
            "low": float(row["Low"]),
            "close": float(row["Close"]),
        })
    return bars, "Yahoo Finance ^VIX"


def fetch_vix() -> dict:
    def _fetch():
        try:
            bars, source = _load_bars()
            if not bars:
                return {"error": "no VIX data"}

            current = bars[-1]["close"]
            now_ms = bars[-1]["date"]

            def _years_ago(years: int) -> int:
                return now_ms - int(years * 365.25 * 86400 * 1000)

            def _days_ago(days: int) -> int:
                return now_ms - int(days * 86400 * 1000)

            slices = {
                "3m": [b for b in bars if b["date"] >= _days_ago(90)],
                "6m": [b for b in bars if b["date"] >= _days_ago(180)],
                "1y": [b for b in bars if b["date"] >= _days_ago(365)],
                "3y": [b for b in bars if b["date"] >= _years_ago(3)],
                "5y": [b for b in bars if b["date"] >= _years_ago(5)],
                "10y": [b for b in bars if b["date"] >= _years_ago(10)],
                "20y": [b for b in bars if b["date"] >= _years_ago(20)],
            }

            def _date_str(ms: int) -> str:
                import datetime
                return datetime.datetime.fromtimestamp(ms / 1000).strftime("%Y-%m-%d")

            stats = {}
            for k, v in slices.items():
                if not v:
                    continue
                closes = [b["close"] for b in v]
                max_bar = max(v, key=lambda b: b["close"])
                stats[k] = {
                    "mean": round(sum(closes) / len(closes), 1),
                    "max": round(max_bar["close"], 1),
                    "min": round(min(closes), 1),
                    "percentile": round(sum(1 for c in closes if c <= current) / len(closes) * 100, 1),
                    "max_date": _date_str(max_bar["date"]),
                }

            # 降采样控制前端渲染性能（短周期数据少，无需降采样）
            def _to_points(bucket):
                return [{"date": b["date"], "value": round(b["close"], 2)} for b in bucket]
            history = {
                "3m": _to_points(slices["3m"]),
                "6m": _to_points(slices["6m"]),
                "1y": _to_points(slices["1y"]),
                "3y": _downsample(_to_points(slices["3y"]), 800),
                "5y": _downsample(_to_points(slices["5y"]), 800),
                "10y": _downsample(_to_points(slices["10y"]), 900),
                "20y": _downsample(_to_points(slices["20y"]), 1000),
            }

            return {
                "error": None,
                "source": source,
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
