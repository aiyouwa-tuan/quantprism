"""Fear & Greed Index data fetcher — CNN (stocks) + Alternative.me (crypto)."""
import time
import httpx

_cache: dict = {}
_TTL = 900  # 15 min


def _cached(key: str, fetch_fn):
    entry = _cache.get(key)
    if entry and time.time() - entry["ts"] < _TTL:
        return entry["data"]
    data = fetch_fn()
    # 错误结果不入缓存，下次立即重试
    if not data.get("error"):
        _cache[key] = {"ts": time.time(), "data": data}
    return data


_CNN_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Referer": "https://www.cnn.com/",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
}

RATING_ZH = {
    "extreme fear": "极度恐惧",
    "fear": "恐惧",
    "neutral": "中性",
    "greed": "贪婪",
    "extreme greed": "极度贪婪",
}


def _color_for_score(score: float) -> str:
    if score <= 25:
        return "#f87171"
    if score <= 45:
        return "#fb923c"
    if score <= 55:
        return "#facc15"
    if score <= 75:
        return "#4ade80"
    return "#22c55e"


def fetch_cnn() -> dict:
    def _fetch():
        try:
            r = httpx.get(
                "https://production.dataviz.cnn.io/index/fearandgreed/graphdata/",
                headers=_CNN_HEADERS,
                timeout=20,
                follow_redirects=True,
            )
            r.raise_for_status()
            d = r.json()
            fg = d.get("fear_and_greed", {})
            hist_raw = d.get("fear_and_greed_historical", {}).get("data", [])
            # Keep last 90 data points
            hist = [
                {
                    "date": int(item["x"]) // 1000,
                    "value": round(item["y"], 1),
                    "rating": item.get("rating", ""),
                }
                for item in hist_raw[-90:]
            ]
            score = round(float(fg.get("score", 0)), 1)
            return {
                "score": score,
                "rating": fg.get("rating", ""),
                "rating_zh": RATING_ZH.get(fg.get("rating", "").lower(), fg.get("rating", "")),
                "color": _color_for_score(score),
                "prev_close": round(float(fg.get("previous_close", 0) or 0), 1),
                "prev_week": round(float(fg.get("previous_1_week", 0) or 0), 1),
                "prev_month": round(float(fg.get("previous_1_month", 0) or 0), 1),
                "prev_year": round(float(fg.get("previous_1_year", 0) or 0), 1),
                "history": hist,
                "error": None,
            }
        except Exception as e:
            return {"error": str(e), "score": 0, "rating": "", "rating_zh": "", "color": "#6b7280", "history": []}

    return _cached("cnn", _fetch)


def fetch_crypto() -> dict:
    def _fetch():
        try:
            r = httpx.get(
                "https://api.alternative.me/fng/?limit=90&format=json",
                timeout=20,
            )
            r.raise_for_status()
            d = r.json()
            items = d.get("data", [])
            hist = [
                {
                    "date": int(item["timestamp"]),
                    "value": int(item["value"]),
                    "rating": item.get("value_classification", ""),
                }
                for item in reversed(items)
            ]
            current = items[0] if items else {}
            score = int(current.get("value", 0))
            rating = current.get("value_classification", "")
            return {
                "score": score,
                "rating": rating,
                "rating_zh": RATING_ZH.get(rating.lower(), rating),
                "color": _color_for_score(score),
                "history": hist,
                "error": None,
            }
        except Exception as e:
            return {"error": str(e), "score": 0, "rating": "", "rating_zh": "", "color": "#6b7280", "history": []}

    return _cached("crypto", _fetch)
