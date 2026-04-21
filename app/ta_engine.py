"""
技术分析引擎
1. 支撑阻力自动识别  — 摆动点聚类 + 成交量评分
2. 海龟交易系统      — System1(20/10) + System2(55/20) + ATR止损
3. 量价背离检测      — 价格新高/低 vs 成交量萎缩
"""
from __future__ import annotations
import statistics
from typing import NamedTuple

# ---------------------------------------------------------------------------
# 数据获取（复用 jin_data 的 SSH 通道）
# ---------------------------------------------------------------------------

TA_SYMBOLS = ["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA",
              "META", "TSLA", "TSM", "QQQ", "SPY"]

_ta_cache: dict = {}
_TA_TTL = 300  # 5 min


def _fetch_candles_raw(symbol: str, limit: int = 300) -> list[dict]:
    """从 VPS 拉取日线数据，返回时间正序列表"""
    import time
    cache_key = f"{symbol}_{limit}"
    now = time.time()
    if cache_key in _ta_cache and now - _ta_cache[cache_key]["ts"] < _TA_TTL:
        return _ta_cache[cache_key]["data"]

    from jin_data import _ssh_query
    sql = f"""
    SELECT DATE(ts)::text AS date,
           open::float8, high::float8, low::float8,
           close::float8, volume::bigint
    FROM stock_candles
    WHERE symbol = '{symbol}.US' AND period = 'day'
    ORDER BY ts DESC LIMIT {limit};
    """
    rows = _ssh_query(sql)
    if not rows:
        return []
    # reverse to chronological order
    data = list(reversed(rows))
    candles = []
    for r in data:
        try:
            candles.append({
                "date":   r["date"],
                "open":   float(r["open"]),
                "high":   float(r["high"]),
                "low":    float(r["low"]),
                "close":  float(r["close"]),
                "volume": int(r["volume"]),
            })
        except (KeyError, ValueError):
            continue

    _ta_cache[cache_key] = {"data": candles, "ts": now}
    return candles


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------

def _atr(candles: list[dict], period: int = 20) -> float:
    """Average True Range"""
    if len(candles) < period + 1:
        return 0.0
    trs = []
    for i in range(1, len(candles)):
        h = candles[i]["high"]
        l = candles[i]["low"]
        pc = candles[i - 1]["close"]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    return sum(trs[-period:]) / period


def _rolling_max(values: list[float], n: int) -> list[float | None]:
    result = []
    for i in range(len(values)):
        if i < n - 1:
            result.append(None)
        else:
            result.append(max(values[i - n + 1: i + 1]))
    return result


def _rolling_min(values: list[float], n: int) -> list[float | None]:
    result = []
    for i in range(len(values)):
        if i < n - 1:
            result.append(None)
        else:
            result.append(min(values[i - n + 1: i + 1]))
    return result


# ===========================================================================
# 1. 支撑阻力识别
# ===========================================================================

def _find_swing_points(candles: list[dict], window: int = 5) -> tuple[list, list]:
    """
    找摆动高点/低点。
    swing_high[i]: candles[i].high 是左右各 window 根K线中的最高点
    swing_low[i]:  candles[i].low  是左右各 window 根K线中的最低点
    """
    highs = [c["high"] for c in candles]
    lows  = [c["low"]  for c in candles]
    n = len(candles)

    swing_highs = []  # (price, index, volume)
    swing_lows  = []

    for i in range(window, n - window):
        left_h  = highs[i - window: i]
        right_h = highs[i + 1: i + window + 1]
        if highs[i] >= max(left_h) and highs[i] >= max(right_h):
            swing_highs.append((highs[i], i, candles[i]["volume"]))

        left_l  = lows[i - window: i]
        right_l = lows[i + 1: i + window + 1]
        if lows[i] <= min(left_l) and lows[i] <= min(right_l):
            swing_lows.append((lows[i], i, candles[i]["volume"]))

    return swing_highs, swing_lows


def _cluster_levels(points: list[tuple], cluster_pct: float = 0.015) -> list[dict]:
    """
    将价格接近的摆动点聚类，输出每个聚类的中心价位和评分。
    评分 = 触碰次数 × 近期权重 × 成交量系数
    """
    if not points:
        return []

    # 按价格排序
    sorted_pts = sorted(points, key=lambda x: x[0])
    clusters: list[list] = []
    cur: list = [sorted_pts[0]]

    for pt in sorted_pts[1:]:
        # 若与当前聚类中心价差 < cluster_pct，归入同一聚类
        center = sum(p[0] for p in cur) / len(cur)
        if abs(pt[0] - center) / center < cluster_pct:
            cur.append(pt)
        else:
            clusters.append(cur)
            cur = [pt]
    clusters.append(cur)

    n_total = len(points)
    result = []
    for cl in clusters:
        prices  = [p[0] for p in cl]
        indices = [p[1] for p in cl]
        vols    = [p[2] for p in cl]

        center_price = sum(prices) / len(prices)
        touch_count  = len(cl)

        # 近期权重：index 越大（越近）权重越高
        recency = sum((idx / n_total) for idx in indices) / touch_count

        # 成交量系数：与平均成交量的比值（此处简化为相对得分）
        avg_vol = sum(vols) / touch_count
        vol_score = min(avg_vol / max(1, max(v for _, _, v in points)), 1.0)

        score = round(touch_count * (0.5 + 0.3 * recency + 0.2 * vol_score), 2)

        result.append({
            "price":       round(center_price, 2),
            "touch_count": touch_count,
            "recency":     round(recency, 2),
            "score":       score,
        })

    return sorted(result, key=lambda x: x["score"], reverse=True)


def calc_support_resistance(symbol: str) -> dict:
    """
    主函数：返回当前价格、支撑位列表（价格以下）、阻力位列表（价格以上）
    """
    candles = _fetch_candles_raw(symbol, 300)
    if len(candles) < 30:
        return {"symbol": symbol, "error": "数据不足"}

    current_price = candles[-1]["close"]
    swing_highs, swing_lows = _find_swing_points(candles, window=5)

    # 阻力位 = 历史摆动高点中高于当前价的
    resistance_pts = [(p, i, v) for p, i, v in swing_highs if p > current_price * 1.001]
    # 支撑位 = 历史摆动低点中低于当前价的
    support_pts    = [(p, i, v) for p, i, v in swing_lows  if p < current_price * 0.999]

    resistances = _cluster_levels(resistance_pts)[:4]
    supports    = _cluster_levels(support_pts)[:4]

    # 按价格排序：支撑由近到远（从高到低），阻力由近到远（从低到高）
    supports    = sorted(supports,    key=lambda x: x["price"], reverse=True)
    resistances = sorted(resistances, key=lambda x: x["price"])

    # 最近支撑距离
    nearest_support    = supports[0]["price"]    if supports    else None
    nearest_resistance = resistances[0]["price"] if resistances else None

    return {
        "symbol":             symbol,
        "current_price":      round(current_price, 2),
        "nearest_support":    nearest_support,
        "nearest_resistance": nearest_resistance,
        "support_distance_pct":    round((current_price - nearest_support)    / current_price * 100, 1) if nearest_support    else None,
        "resistance_distance_pct": round((nearest_resistance - current_price) / current_price * 100, 1) if nearest_resistance else None,
        "supports":    supports,
        "resistances": resistances,
        "candle_count": len(candles),
    }


# ===========================================================================
# 2. 海龟交易系统
# ===========================================================================

def calc_turtle(symbol: str) -> dict:
    """
    System1: 20日突破入场, 10日通道出场
    System2: 55日突破入场, 20日通道出场
    ATR(20) 止损 = 入场价 - 2×ATR
    仓位单位 = 账户净值×1% / (ATR×每股价格)  （以 $100,000 账户为例）
    """
    candles = _fetch_candles_raw(symbol, 100)
    if len(candles) < 60:
        return {"symbol": symbol, "error": "数据不足"}

    highs  = [c["high"]  for c in candles]
    lows   = [c["low"]   for c in candles]
    closes = [c["close"] for c in candles]
    current = closes[-1]
    atr20   = _atr(candles, 20)

    # Donchian 通道
    high20  = max(highs[-21:-1])   # 前20日高点（不含今日）
    low10   = min(lows[-11:-1])    # 前10日低点
    high55  = max(highs[-56:-1])   # 前55日高点
    low20   = min(lows[-21:-1])    # 前20日低点
    low55   = min(lows[-56:-1])    # 前55日低点（空头入场）
    high20e = max(highs[-21:-1])   # System2 多头出场

    # System1 信号
    s1_long_entry  = current > high20
    s1_long_exit   = current < low10
    s1_short_entry = current < min(lows[-21:-1])

    # System2 信号
    s2_long_entry  = current > high55
    s2_long_exit   = current < low20
    s2_short_entry = current < low55

    def _state(entry: bool, exit_: bool) -> str:
        if entry:  return "突破入场"
        if exit_:  return "出场信号"
        return "观望"

    s1_state = _state(s1_long_entry, s1_long_exit)
    s2_state = _state(s2_long_entry, s2_long_exit)

    # 综合建议
    if s2_long_entry:
        recommendation = "买入"
        detail = f"价格突破 55 日高点 ${high55:.2f}，System2 入场信号"
    elif s2_long_exit:
        recommendation = "止盈出场"
        detail = f"价格跌破 20 日低点 ${low20:.2f}，多头平仓"
    elif s1_long_entry:
        recommendation = "试探买入"
        detail = f"价格突破 20 日高点 ${high20:.2f}，System1 入场信号（较弱）"
    elif s1_long_exit:
        recommendation = "减仓"
        detail = f"价格跌破 10 日低点 ${low10:.2f}，System1 出场"
    else:
        recommendation = "观望"
        detail = f"价格在通道内，等待突破"

    # 止损与仓位计算（示例账户 $100,000）
    stop_loss  = round(current - 2 * atr20, 2) if atr20 else None
    risk_per_share = 2 * atr20 if atr20 else 0
    unit_shares = int(100_000 * 0.01 / risk_per_share) if risk_per_share > 0 else 0

    return {
        "symbol":         symbol,
        "current_price":  round(current, 2),
        "atr20":          round(atr20, 2),
        "system1": {
            "entry_level":  round(high20, 2),
            "exit_level":   round(low10, 2),
            "state":        s1_state,
            "description":  "20日高点突破入场，10日低点出场",
        },
        "system2": {
            "entry_level":  round(high55, 2),
            "exit_level":   round(low20, 2),
            "state":        s2_state,
            "description":  "55日高点突破入场，20日低点出场",
        },
        "recommendation": recommendation,
        "detail":         detail,
        "risk_management": {
            "stop_loss":          stop_loss,
            "stop_distance_pct":  round((current - stop_loss) / current * 100, 1) if stop_loss else None,
            "unit_shares":        unit_shares,
            "unit_risk_usd":      round(unit_shares * risk_per_share, 0) if unit_shares else 0,
            "note":               "以 $100,000 账户、1% 风险/单位计算",
        },
    }


# ===========================================================================
# 3. 量价背离检测
# ===========================================================================

def calc_divergence(symbol: str) -> dict:
    """
    检测量价背离：
    - 顶部警告：价格创 N 日新高，但成交量低于近 N 日均量×阈值
    - 底部参考：价格创 N 日新低，但成交量低于近 N 日均量×阈值
    - 连续检测 lookback 天，统计强度
    """
    candles = _fetch_candles_raw(symbol, 80)
    if len(candles) < 25:
        return {"symbol": symbol, "error": "数据不足"}

    PRICE_WINDOW = 20     # 价格新高/低的回望窗口
    VOL_WINDOW   = 20     # 均量计算窗口
    VOL_THRESHOLD = 0.85  # 成交量低于均量的比例阈值（<85% 视为萎缩）
    SCAN_DAYS    = 5      # 扫描最近几天找信号

    closes  = [c["close"]  for c in candles]
    volumes = [c["volume"] for c in candles]
    dates   = [c["date"]   for c in candles]

    signals = []

    for i in range(PRICE_WINDOW, len(candles)):
        price_window_high = max(closes[i - PRICE_WINDOW: i])
        price_window_low  = min(closes[i - PRICE_WINDOW: i])
        avg_vol = sum(volumes[i - VOL_WINDOW: i]) / VOL_WINDOW
        cur_vol = volumes[i]
        cur_close = closes[i]
        vol_shrinking = cur_vol < avg_vol * VOL_THRESHOLD
        vol_ratio = round(cur_vol / avg_vol, 2)

        if cur_close >= price_window_high and vol_shrinking:
            signals.append({
                "date":        dates[i],
                "type":        "bearish",
                "label":       "顶部警告",
                "description": f"价格 ${cur_close:.2f} 创 {PRICE_WINDOW} 日新高，成交量仅为均量的 {vol_ratio*100:.0f}%（萎缩）",
                "close":       round(cur_close, 2),
                "volume":      cur_vol,
                "avg_volume":  round(avg_vol),
                "vol_ratio":   vol_ratio,
            })
        elif cur_close <= price_window_low and vol_shrinking:
            signals.append({
                "date":        dates[i],
                "type":        "bullish",
                "label":       "底部参考",
                "description": f"价格 ${cur_close:.2f} 创 {PRICE_WINDOW} 日新低，成交量仅为均量的 {vol_ratio*100:.0f}%（萎缩）",
                "close":       round(cur_close, 2),
                "volume":      cur_vol,
                "avg_volume":  round(avg_vol),
                "vol_ratio":   vol_ratio,
            })

    recent_signals = [s for s in signals if s["date"] >= dates[-SCAN_DAYS]]
    latest = signals[-1] if signals else None

    # 强度评估：最近 20 根K线内出现多少次信号
    recent20 = [s for s in signals if s["date"] >= dates[-20]]
    bearish_count = sum(1 for s in recent20 if s["type"] == "bearish")
    bullish_count = sum(1 for s in recent20 if s["type"] == "bullish")

    if bearish_count >= 3:
        strength = "强"
        overall  = "持续顶部背离，警惕回调"
    elif bullish_count >= 3:
        strength = "强"
        overall  = "持续底部背离，关注企稳"
    elif recent_signals:
        strength = "弱"
        overall  = recent_signals[-1]["label"] + "（单次信号）"
    else:
        strength = "无"
        overall  = "近期无量价背离"

    return {
        "symbol":          symbol,
        "current_price":   round(closes[-1], 2),
        "current_volume":  volumes[-1],
        "avg_volume_20d":  round(sum(volumes[-20:]) / 20),
        "overall":         overall,
        "strength":        strength,
        "recent_signals":  recent_signals,
        "bearish_count_20d": bearish_count,
        "bullish_count_20d": bullish_count,
        "all_signal_count":  len(signals),
        "latest_signal":   latest,
    }


# ===========================================================================
# 汇总：全量扫描
# ===========================================================================

def calc_ta_summary() -> list[dict]:
    """扫描全部 10 支标的，返回每支的三维信号摘要"""
    import time
    cache_key = "ta_summary"
    now = time.time()
    if cache_key in _ta_cache and now - _ta_cache[cache_key]["ts"] < _TA_TTL:
        return _ta_cache[cache_key]["data"]

    results = []
    for sym in TA_SYMBOLS:
        try:
            sr  = calc_support_resistance(sym)
            trt = calc_turtle(sym)
            div = calc_divergence(sym)

            results.append({
                "symbol": sym,
                "price":  sr.get("current_price"),
                "support_resistance": {
                    "nearest_support":         sr.get("nearest_support"),
                    "nearest_resistance":       sr.get("nearest_resistance"),
                    "support_distance_pct":     sr.get("support_distance_pct"),
                    "resistance_distance_pct":  sr.get("resistance_distance_pct"),
                },
                "turtle": {
                    "recommendation": trt.get("recommendation"),
                    "detail":         trt.get("detail"),
                    "stop_loss":      trt.get("risk_management", {}).get("stop_loss"),
                    "s1_state":       trt.get("system1", {}).get("state"),
                    "s2_state":       trt.get("system2", {}).get("state"),
                },
                "divergence": {
                    "overall":  div.get("overall"),
                    "strength": div.get("strength"),
                },
            })
        except Exception as e:
            results.append({"symbol": sym, "error": str(e)})

    _ta_cache[cache_key] = {"data": results, "ts": now}
    return results
