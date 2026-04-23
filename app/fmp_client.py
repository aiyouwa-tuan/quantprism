"""FMP (Financial Modeling Prep) 免费层客户端 — QQQ Top10 持仓历史 PE/PB/股息率。

免费层限制：
- ETF 的 /ratios 端点 402 付费限制（QQQ 直接拿不到）
- 单个股票的 /ratios 端点可用，返回 5 年年报数据
- 所以曲线方式：拉 Top 10 持仓每只的年度 PE/PB → 按权重加权近似 QQQ

限额：250 次/天，15 min 缓存 + 合并请求 → 每天最多 ~10 次刷新
"""
import os
import time
import httpx

_cache: dict = {}
_TTL = 3600  # 1 小时（年报数据，无需频繁刷新）

# QQQ 截至 2026-04 Top 10 持仓（Invesco 官方披露的近似权重）
# 合计约占 QQQ 市值 51%
QQQ_TOP10 = [
    ("AAPL", "苹果",   0.085),
    ("NVDA", "英伟达", 0.082),
    ("MSFT", "微软",   0.078),
    ("AMZN", "亚马逊", 0.055),
    ("META", "Meta",  0.050),
    ("AVGO", "博通",   0.050),
    ("TSLA", "特斯拉", 0.038),
    ("COST", "好市多", 0.028),
    ("GOOGL","谷歌A", 0.027),
    ("GOOG", "谷歌C", 0.025),
]


def _cached(key, fn):
    entry = _cache.get(key)
    if entry and time.time() - entry["ts"] < _TTL:
        return entry["data"]
    data = fn()
    if not data.get("error"):
        _cache[key] = {"ts": time.time(), "data": data}
    return data


def _fetch_ratios(symbol: str, api_key: str) -> list:
    """拉单个股票的年报 ratios（PE/PB/股息率/ROE 估算）"""
    url = f"https://financialmodelingprep.com/stable/ratios?symbol={symbol}&apikey={api_key}"
    r = httpx.get(url, timeout=15)
    if r.status_code != 200:
        return []
    d = r.json()
    # 归一化需要的字段
    out = []
    for item in d:
        out.append({
            "date": item.get("date"),
            "fiscal_year": item.get("fiscalYear"),
            "pe": item.get("priceToEarningsRatio"),
            "pb": item.get("priceToBookRatio"),
            "dividend_yield_pct": round((item.get("dividendYieldPercentage") or 0) * 100, 2) if item.get("dividendYieldPercentage") and item.get("dividendYieldPercentage") < 1 else item.get("dividendYieldPercentage"),
            "net_income_per_share": item.get("netIncomePerShare"),
            "book_value_per_share": item.get("bookValuePerShare"),
        })
    return out


def fetch_qqq_top10_history() -> dict:
    """拉 Top 10 持仓每家的 5 年 PE/PB + 按权重加权近似 QQQ。"""
    def _fetch():
        api_key = os.environ.get("FMP_API_KEY")
        if not api_key:
            return {"error": "FMP_API_KEY 未配置"}

        holdings = []
        for sym, name_zh, weight in QQQ_TOP10:
            try:
                ratios = _fetch_ratios(sym, api_key)
                if ratios:
                    holdings.append({
                        "symbol": sym,
                        "name_zh": name_zh,
                        "weight": weight,
                        "ratios": ratios,  # 最多 5 条，按日期倒序
                    })
            except Exception as e:
                # 单个失败不阻塞其他
                holdings.append({"symbol": sym, "name_zh": name_zh, "weight": weight, "ratios": [], "error": str(e)})

        if not holdings or not any(h.get("ratios") for h in holdings):
            return {"error": "all holdings failed to fetch"}

        # 建立年度表：year -> {weighted_pe, weighted_pb, coverage}
        # 用 fiscalYear 对齐
        years_set = set()
        for h in holdings:
            for r in h.get("ratios", []):
                if r.get("fiscal_year"):
                    years_set.add(r["fiscal_year"])
        years = sorted(years_set)

        weighted_series = []
        for year in years:
            sum_pe_w = 0.0
            sum_pb_w = 0.0
            sum_dy_w = 0.0
            total_weight = 0.0
            constituents = []
            for h in holdings:
                match = next((r for r in h["ratios"] if r.get("fiscal_year") == year), None)
                if match and match.get("pe") and match["pe"] > 0:
                    w = h["weight"]
                    sum_pe_w += float(match["pe"]) * w
                    if match.get("pb") and match["pb"] > 0:
                        sum_pb_w += float(match["pb"]) * w
                    if match.get("dividend_yield_pct") is not None:
                        sum_dy_w += float(match["dividend_yield_pct"]) * w
                    total_weight += w
                    constituents.append({
                        "symbol": h["symbol"],
                        "name_zh": h["name_zh"],
                        "pe": round(float(match["pe"]), 1),
                        "weight": w,
                        "date": match.get("date"),
                    })
            if total_weight > 0:
                weighted_series.append({
                    "year": year,
                    "pe_weighted": round(sum_pe_w / total_weight, 1),
                    "pb_weighted": round(sum_pb_w / total_weight, 2) if sum_pb_w > 0 else None,
                    "div_yield_weighted": round(sum_dy_w / total_weight, 2),
                    "coverage_pct": round(total_weight * 100, 1),  # Top10 中多少比例命中
                    "constituents": constituents,
                })

        # 个股矩阵（用于前端画多线）
        matrix = []
        for h in holdings:
            matrix.append({
                "symbol": h["symbol"],
                "name_zh": h["name_zh"],
                "weight": h["weight"],
                "points": [
                    {"year": r["fiscal_year"], "pe": r["pe"], "pb": r.get("pb"), "date": r["date"]}
                    for r in h.get("ratios", [])
                    if r.get("pe") and r["pe"] > 0
                ],
            })

        return {
            "error": None,
            "source": "FMP /stable/ratios（免费层）",
            "holdings_count": len([h for h in holdings if h.get("ratios")]),
            "weighted": weighted_series,  # 加权近似 QQQ
            "matrix": matrix,              # 个股原始
            "top10_total_weight": round(sum(w for _, _, w in QQQ_TOP10) * 100, 1),
        }

    return _cached("fmp_qqq_top10", _fetch)
