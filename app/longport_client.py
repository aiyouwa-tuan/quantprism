"""长桥 OpenAPI 客户端 — 市场温度（温度/估值/情绪 三层）

环境变量：
  LONGPORT_APP_KEY
  LONGPORT_APP_SECRET
  LONGPORT_ACCESS_TOKEN
"""
import os
import time
from datetime import date, timedelta

_cache: dict = {}
_TTL = 900  # 15 min
_ctx = None


def _get_ctx():
    """Lazy init QuoteContext — 重用长连接。"""
    global _ctx
    if _ctx is not None:
        return _ctx
    try:
        from longport.openapi import Config, QuoteContext
        config = Config.from_env()
        _ctx = QuoteContext(config)
        return _ctx
    except Exception as e:
        raise RuntimeError(f"LongPort init failed: {e}")


def _cached(key, fn):
    entry = _cache.get(key)
    if entry and time.time() - entry["ts"] < _TTL:
        return entry["data"]
    data = fn()
    if not data.get("error"):
        _cache[key] = {"ts": time.time(), "data": data}
    return data


def _market_enum(market: str):
    from longport.openapi import Market
    m = market.upper()
    return {"US": Market.US, "HK": Market.HK, "CN": Market.CN}[m]


def _score_color(score: float) -> str:
    """温度/估值/情绪的配色 — 和 CNN F&G 保持一致。"""
    if score <= 25: return "#f87171"
    if score <= 45: return "#fb923c"
    if score <= 55: return "#facc15"
    if score <= 75: return "#4ade80"
    return "#22c55e"


def fetch_vix_history() -> list:
    """VIX 日线历史 — 长桥 .VIX.US。分段拉（每次最多 1000 条）。

    返回：[{date: ms_ts, open, high, low, close}, ...] 升序
    """
    def _fetch():
        try:
            from longport.openapi import Period, AdjustType
            from datetime import date, timedelta
            ctx = _get_ctx()
            # 分 3 年段拉 2006-现在 约 7 段
            all_bars = []
            today = date.today()
            # 起点 2006 年
            end = today + timedelta(days=1)
            while end > date(2005, 1, 1):
                start = date(max(2005, end.year - 3), 1, 1)
                bars = ctx.history_candlesticks_by_date(
                    ".VIX.US", Period.Day, AdjustType.NoAdjust, start, end
                )
                if not bars:
                    break
                all_bars.extend(bars)
                # 下一段：把 end 设为当前段最早的一天
                earliest = min(b.timestamp for b in bars).date()
                if earliest >= end:
                    break
                end = earliest - timedelta(days=1)
                if len(all_bars) > 6000:
                    break
            # 去重 + 排序
            seen = set()
            unique = []
            for b in all_bars:
                ts = b.timestamp
                if ts not in seen:
                    seen.add(ts)
                    unique.append(b)
            unique.sort(key=lambda b: b.timestamp)
            return {
                "error": None,
                "source": "longport",
                "bars": [
                    {
                        "date": int(b.timestamp.timestamp() * 1000),
                        "open": float(b.open),
                        "high": float(b.high),
                        "low": float(b.low),
                        "close": float(b.close),
                    }
                    for b in unique
                ],
            }
        except Exception as e:
            return {"error": str(e), "source": "longport", "bars": []}

    return _cached("lp_vix", _fetch)


def fetch_market_temperature(market: str = "US") -> dict:
    """拉取指定市场的当前温度 + 一年历史。"""
    def _fetch():
        try:
            ctx = _get_ctx()
            mk = _market_enum(market)

            # 当前快照
            current = ctx.market_temperature(mk)
            temp = int(current.temperature)
            val = int(current.valuation)
            sent = int(current.sentiment)
            desc = str(current.description or "")

            # 历史 1 年
            today = date.today()
            start = today - timedelta(days=365)
            hist_resp = ctx.history_market_temperature(mk, start, today)
            records = []
            for r in hist_resp.records:
                ts = r.timestamp
                records.append({
                    "date": int(ts.timestamp() * 1000) if hasattr(ts, "timestamp") else 0,
                    "temperature": int(r.temperature),
                    "valuation": int(r.valuation),
                    "sentiment": int(r.sentiment),
                })
            # 按时间升序（旧→新）
            records.sort(key=lambda x: x["date"])

            return {
                "error": None,
                "market": market.upper(),
                "current": {
                    "temperature": temp,
                    "valuation": val,
                    "sentiment": sent,
                    "description": desc,
                    "temp_color": _score_color(temp),
                    "val_color": _score_color(val),
                    "sent_color": _score_color(sent),
                },
                "history": records,
            }
        except Exception as e:
            return {"error": str(e), "market": market.upper()}

    return _cached(f"lp_temp_{market}", _fetch)
