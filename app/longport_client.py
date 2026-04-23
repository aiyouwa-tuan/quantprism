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
