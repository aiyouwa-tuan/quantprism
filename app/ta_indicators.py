"""
ta_indicators.py — 技术分析指标库（墨菲《期货市场技术分析》体系）

P0: RSI / MACD / ADX+DMI / Fibonacci / 道氏三级趋势
P1: 布林带 / 缺口识别 / 趋势线 / 量价四象限 / 吹顶卖出高潮
P2: 头肩顶底 / 双顶双底 / 三角形 / 旗形楔形 / Stochastic / Momentum-ROC
P3: 三重顶底圆弧底 / CCI / Parabolic SAR / 矩形箱体
combined_signal(): 综合加权信号
"""
from __future__ import annotations
import math
import statistics
from typing import Optional

# ---------------------------------------------------------------------------
# 数据获取（复用 ta_engine 缓存）
# ---------------------------------------------------------------------------

_ind_cache: dict = {}
_IND_TTL = 300  # 5 min


def _get_candles(symbol: str, limit: int = 300) -> list[dict]:
    """从 VPS 拉取日线数据（5 分钟缓存）"""
    import time
    key = f"ind_{symbol}_{limit}"
    now = time.time()
    if key in _ind_cache and now - _ind_cache[key]["ts"] < _IND_TTL:
        return _ind_cache[key]["data"]

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
    data = []
    for r in reversed(rows):
        try:
            data.append({
                "date":   r["date"],
                "open":   float(r["open"]),
                "high":   float(r["high"]),
                "low":    float(r["low"]),
                "close":  float(r["close"]),
                "volume": int(r["volume"]),
            })
        except (KeyError, ValueError):
            continue
    _ind_cache[key] = {"data": data, "ts": now}
    return data


def clear_cache():
    _ind_cache.clear()


# ---------------------------------------------------------------------------
# 内部工具
# ---------------------------------------------------------------------------

def _ema(values: list[float], period: int) -> list[float]:
    """指数移动平均，返回与 values 等长列表（前 period-1 个元素填 0.0）"""
    k = 2.0 / (period + 1)
    result = [0.0] * len(values)
    if len(values) < period:
        return result
    result[period - 1] = sum(values[:period]) / period
    for i in range(period, len(values)):
        result[i] = values[i] * k + result[i - 1] * (1 - k)
    return result


def _sma(values: list[float], period: int) -> list[Optional[float]]:
    result: list[Optional[float]] = [None] * len(values)
    for i in range(period - 1, len(values)):
        result[i] = sum(values[i - period + 1: i + 1]) / period
    return result


def _stddev(values: list[float], period: int) -> list[Optional[float]]:
    result: list[Optional[float]] = [None] * len(values)
    for i in range(period - 1, len(values)):
        window = values[i - period + 1: i + 1]
        mean = sum(window) / period
        var = sum((x - mean) ** 2 for x in window) / period
        result[i] = math.sqrt(var)
    return result


def _tr(candles: list[dict]) -> list[float]:
    """True Range 列表"""
    trs = []
    for i in range(len(candles)):
        h = candles[i]["high"]
        l = candles[i]["low"]
        pc = candles[i - 1]["close"] if i > 0 else candles[i]["close"]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    return trs


def _atr(candles: list[dict], period: int = 14) -> float:
    trs = _tr(candles)
    if len(trs) < period:
        return 0.0
    return sum(trs[-period:]) / period


def _signal(value, buy_thr, sell_thr, higher_is_buy=True):
    """通用方向信号"""
    if higher_is_buy:
        if value >= buy_thr: return "buy"
        if value <= sell_thr: return "sell"
    else:
        if value <= buy_thr: return "buy"
        if value >= sell_thr: return "sell"
    return "neutral"


def _conf(value: float, low=0.3, high=0.7) -> str:
    if value >= high: return "high"
    if value >= low:  return "medium"
    return "low"


def _find_swing_points(candles: list[dict], window: int = 5):
    highs = [c["high"] for c in candles]
    lows  = [c["low"]  for c in candles]
    n = len(candles)
    sh, sl = [], []
    for i in range(window, n - window):
        if highs[i] >= max(highs[i - window: i]) and highs[i] >= max(highs[i + 1: i + window + 1]):
            sh.append((highs[i], i, candles[i]["volume"]))
        if lows[i] <= min(lows[i - window: i]) and lows[i] <= min(lows[i + 1: i + window + 1]):
            sl.append((lows[i], i, candles[i]["volume"]))
    return sh, sl


# ===========================================================================
# P0 — 振荡器 / 趋势类核心指标
# ===========================================================================

# --- 1. RSI(14) ---

def calc_rsi(candles: list[dict], period: int = 14) -> dict:
    closes = [c["close"] for c in candles]
    if len(closes) < period + 1:
        return {"error": "数据不足"}

    gains, losses = [], []
    for i in range(1, len(closes)):
        diff = closes[i] - closes[i - 1]
        gains.append(max(diff, 0))
        losses.append(max(-diff, 0))

    # Wilder 平滑
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    rsi_values = []
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        rs = avg_gain / avg_loss if avg_loss > 0 else 100
        rsi_values.append(100 - 100 / (1 + rs))

    current_rsi = round(rsi_values[-1], 1)

    # 背离：近10根K线内价格创新高但RSI未新高
    lookback = min(10, len(rsi_values) - 1)
    price_new_high = closes[-1] > max(closes[-lookback - 1:-1])
    rsi_new_high   = rsi_values[-1] > max(rsi_values[-lookback - 1:-1])
    price_new_low  = closes[-1] < min(closes[-lookback - 1:-1])
    rsi_new_low    = rsi_values[-1] < min(rsi_values[-lookback - 1:-1])

    divergence = None
    if price_new_high and not rsi_new_high:
        divergence = "顶背离（价格新高 RSI 未新高）"
    elif price_new_low and not rsi_new_low:
        divergence = "底背离（价格新低 RSI 未新低）"

    if current_rsi > 70:
        sig, desc = "sell", f"RSI {current_rsi} 超买区域（>70），短期上涨动能衰减"
        conf_val = 0.6 if current_rsi > 80 else 0.45
    elif current_rsi < 30:
        sig, desc = "buy", f"RSI {current_rsi} 超卖区域（<30），反弹机会增加"
        conf_val = 0.6 if current_rsi < 20 else 0.45
    else:
        sig, desc = "neutral", f"RSI {current_rsi} 中性区间，趋势延续"
        conf_val = 0.3

    if divergence:
        sig = "sell" if "顶" in divergence else "buy"
        desc = divergence
        conf_val = 0.65

    return {
        "value": current_rsi,
        "signal": sig,
        "description": desc,
        "confidence": _conf(conf_val),
        "divergence": divergence,
        "overbought": current_rsi > 70,
        "oversold": current_rsi < 30,
    }


# --- 2. MACD(12,26,9) ---

def calc_macd(candles: list[dict]) -> dict:
    closes = [c["close"] for c in candles]
    if len(closes) < 35:
        return {"error": "数据不足"}

    ema12 = _ema(closes, 12)
    ema26 = _ema(closes, 26)
    macd_line = [ema12[i] - ema26[i] for i in range(len(closes))]
    # 从第26个有效
    valid_macd = [v for i, v in enumerate(macd_line) if ema26[i] != 0.0]
    if len(valid_macd) < 9:
        return {"error": "数据不足"}

    # signal line = 9日EMA of MACD
    signal_vals = _ema(valid_macd, 9)
    hist = [valid_macd[i] - signal_vals[i] for i in range(len(valid_macd))]

    cur_hist   = round(hist[-1], 4)
    cur_macd   = round(valid_macd[-1], 4)
    cur_signal = round(signal_vals[-1], 4)
    prev_hist  = hist[-2] if len(hist) > 1 else hist[-1]

    # 金叉/死叉
    cross = "neutral"
    if valid_macd[-1] > signal_vals[-1] and valid_macd[-2] <= signal_vals[-2]:
        cross = "golden_cross"
    elif valid_macd[-1] < signal_vals[-1] and valid_macd[-2] >= signal_vals[-2]:
        cross = "death_cross"

    # 柱子由负转正的日期
    hist_turn_date = None
    for i in range(len(hist) - 1, 0, -1):
        if hist[i] > 0 and hist[i - 1] <= 0:
            # 找到对应日期
            offset = len(closes) - len(valid_macd) + i
            if offset < len(candles):
                hist_turn_date = candles[offset]["date"]
            break

    # 底背离：价格新低但MACD柱未新低
    lookback = min(20, len(hist) - 1)
    price_new_low = closes[-1] < min(closes[-lookback - 1:-1])
    hist_new_low  = hist[-1] < min(hist[-lookback - 1:-1])
    divergence = None
    if price_new_low and not hist_new_low and hist[-1] < 0:
        divergence = "底背离（价格新低 MACD 柱未新低）"

    if cross == "golden_cross":
        sig, desc = "buy", "MACD 金叉（MACD线上穿信号线），多头动能增强"
        conf_val = 0.65
    elif cross == "death_cross":
        sig, desc = "sell", "MACD 死叉（MACD线下穿信号线），空头动能增强"
        conf_val = 0.65
    elif cur_hist > 0 and prev_hist < 0:
        sig, desc = "buy", "MACD 柱由负转正，趋势可能反转向上"
        conf_val = 0.55
    elif cur_hist < 0 and prev_hist > 0:
        sig, desc = "sell", "MACD 柱由正转负，趋势可能反转向下"
        conf_val = 0.55
    elif cur_hist > 0:
        sig, desc = "neutral", f"MACD 柱正值（{cur_hist}），多头趋势延续"
        conf_val = 0.35
    else:
        sig, desc = "neutral", f"MACD 柱负值（{cur_hist}），空头趋势延续"
        conf_val = 0.35

    if divergence:
        sig, desc = "buy", divergence
        conf_val = 0.65

    return {
        "value": cur_hist,
        "macd": cur_macd,
        "signal_line": cur_signal,
        "signal": sig,
        "description": desc,
        "confidence": _conf(conf_val),
        "cross": cross,
        "hist_turn_date": hist_turn_date,
        "divergence": divergence,
    }


# --- 3. ADX + DMI ---

def calc_adx(candles: list[dict], period: int = 14) -> dict:
    if len(candles) < period * 2 + 1:
        return {"error": "数据不足"}

    plus_dm_list, minus_dm_list, tr_list = [], [], []
    for i in range(1, len(candles)):
        h, l = candles[i]["high"], candles[i]["low"]
        ph, pl = candles[i-1]["high"], candles[i-1]["low"]
        pc = candles[i-1]["close"]
        up_move   = h - ph
        down_move = pl - l
        plus_dm_list.append(up_move   if up_move > down_move and up_move > 0   else 0.0)
        minus_dm_list.append(down_move if down_move > up_move and down_move > 0 else 0.0)
        tr_list.append(max(h - l, abs(h - pc), abs(l - pc)))

    def _wilder_smooth(vals, p):
        """Wilder 平滑（前 p 个均值，后续 EMA 方式）"""
        res = [0.0] * len(vals)
        if len(vals) < p:
            return res
        res[p - 1] = sum(vals[:p])
        for i in range(p, len(vals)):
            res[i] = res[i - 1] - res[i - 1] / p + vals[i]
        return res

    atr_s = _wilder_smooth(tr_list, period)
    pdm_s = _wilder_smooth(plus_dm_list, period)
    mdm_s = _wilder_smooth(minus_dm_list, period)

    dx_list = []
    pdi_list, mdi_list = [], []
    for i in range(period - 1, len(atr_s)):
        if atr_s[i] == 0:
            continue
        pdi = 100 * pdm_s[i] / atr_s[i]
        mdi = 100 * mdm_s[i] / atr_s[i]
        pdi_list.append(pdi)
        mdi_list.append(mdi)
        denom = pdi + mdi
        dx_list.append(100 * abs(pdi - mdi) / denom if denom > 0 else 0)

    if len(dx_list) < period:
        return {"error": "数据不足"}

    # ADX = Wilder smooth of DX
    adx_list = []
    adx_list.append(sum(dx_list[:period]) / period)
    for i in range(period, len(dx_list)):
        adx_list.append((adx_list[-1] * (period - 1) + dx_list[i]) / period)

    adx  = round(adx_list[-1], 1)
    pdi  = round(pdi_list[-1], 1)
    mdi  = round(mdi_list[-1], 1)

    # 金叉/死叉
    di_cross = "neutral"
    if len(pdi_list) > 1:
        if pdi_list[-1] > mdi_list[-1] and pdi_list[-2] <= mdi_list[-2]:
            di_cross = "bullish_cross"
        elif pdi_list[-1] < mdi_list[-1] and pdi_list[-2] >= mdi_list[-2]:
            di_cross = "bearish_cross"

    trending = adx > 25

    if adx > 25 and pdi > mdi:
        sig  = "buy"
        desc = f"ADX {adx} 趋势强（>25），+DI>{-mdi}，多头趋势确立"
    elif adx > 25 and pdi < mdi:
        sig  = "sell"
        desc = f"ADX {adx} 趋势强（>25），-DI>{pdi}，空头趋势确立"
    elif adx < 20:
        sig  = "watch"
        desc = f"ADX {adx} 震荡市（<20），趋势信号可靠性低，海龟突破大概率假突破"
    else:
        sig  = "neutral"
        desc = f"ADX {adx} 趋势温和，方向待确认"

    conf_val = 0.7 if adx > 30 else (0.45 if adx > 25 else 0.25)

    return {
        "value": adx,
        "plus_di": pdi,
        "minus_di": mdi,
        "signal": sig,
        "description": desc,
        "confidence": _conf(conf_val),
        "trending": trending,
        "di_cross": di_cross,
    }


# --- 4. Fibonacci 回撤 ---

def calc_fibonacci(candles: list[dict], lookback: int = 200) -> dict:
    recent = candles[-lookback:] if len(candles) >= lookback else candles
    highs  = [c["high"]  for c in recent]
    lows   = [c["low"]   for c in recent]
    closes = [c["close"] for c in candles]

    swing_high = max(highs)
    swing_low  = min(lows)
    current    = closes[-1]
    hi_idx     = highs.index(swing_high)
    lo_idx     = lows.index(swing_low)

    # 方向：高点在后 = 上涨后回调，低点在后 = 下跌后反弹
    direction = "retracement_down" if hi_idx > lo_idx else "retracement_up"
    span = swing_high - swing_low

    ratios = [0.0, 0.236, 0.382, 0.500, 0.618, 0.786, 1.0]
    if direction == "retracement_down":
        levels = {str(r): round(swing_high - span * r, 2) for r in ratios}
    else:
        levels = {str(r): round(swing_low + span * r, 2) for r in ratios}

    # 当前价在哪两个 Fib 位之间
    sorted_levels = sorted(levels.values())
    position_below = max((v for v in sorted_levels if v <= current), default=sorted_levels[0])
    position_above = min((v for v in sorted_levels if v >= current), default=sorted_levels[-1])

    below_pct = round((current - position_below) / current * 100, 1) if current > 0 else 0
    above_pct = round((position_above - current) / current * 100, 1) if current > 0 else 0

    # 判断最近支撑
    fib_support = max((v for v in sorted_levels if v < current * 0.998), default=None)
    fib_resist  = min((v for v in sorted_levels if v > current * 1.002), default=None)

    return {
        "swing_high": round(swing_high, 2),
        "swing_low":  round(swing_low, 2),
        "direction":  direction,
        "levels":     {k: round(v, 2) for k, v in levels.items()},
        "current_price": round(current, 2),
        "position_below": position_below,
        "position_above": position_above,
        "distance_to_below_pct": below_pct,
        "distance_to_above_pct": above_pct,
        "nearest_fib_support": fib_support,
        "nearest_fib_resistance": fib_resist,
        "signal": "neutral",
        "description": f"当前价 ${current:.2f} 在 Fib {position_below} 与 {position_above} 之间，距下方支撑 {below_pct}%",
        "confidence": "medium",
    }


# --- 5. 道氏三级趋势 ---

def calc_dow_theory(candles: list[dict]) -> dict:
    closes  = [c["close"]  for c in candles]
    volumes = [c["volume"] for c in candles]

    def _trend(ma_short, ma_long, price_window) -> str:
        if len(closes) < ma_long:
            return "Neutral"
        # MA方向
        ma_s = _sma(closes, ma_short)
        ma_l = _sma(closes, ma_long)
        idx  = -1
        while ma_l[idx] is None:
            idx -= 1
        ma_up = ma_s[idx] is not None and ma_s[idx] > ma_l[idx]  # type: ignore
        # 价格方向：比较 price_window 前
        pw_idx = max(-price_window, -len(closes))
        price_up = closes[-1] > closes[pw_idx]
        if ma_up and price_up:   return "Up"
        if not ma_up and not price_up: return "Down"
        return "Neutral"

    primary   = _trend(50, 200, 120)  # 6月价格
    secondary = _trend(20, 50,  20)   # 1月价格
    minor     = _trend(5,  20,  5)    # 1周价格

    # 成交量确认：主趋势上涨时最近30日均量 vs 前30日均量
    vol_confirm = None
    if len(volumes) >= 60:
        recent_vol = sum(volumes[-30:]) / 30
        prior_vol  = sum(volumes[-60:-30]) / 30
        if primary == "Up":
            vol_confirm = recent_vol > prior_vol
        elif primary == "Down":
            vol_confirm = recent_vol > prior_vol

    # 综合判断
    score = sum([
        1 if primary == "Up" else (-1 if primary == "Down" else 0),
        0.5 if secondary == "Up" else (-0.5 if secondary == "Down" else 0),
        0.3 if minor == "Up" else (-0.3 if minor == "Down" else 0),
    ])
    if vol_confirm:
        score += 0.2 if primary == "Up" else -0.2

    if score > 1.2:
        sig  = "buy"
        desc = f"主/次/小趋势全面向上，{'成交量确认' if vol_confirm else '等待量能配合'}"
        conf_val = 0.75
    elif score < -1.2:
        sig  = "sell"
        desc = f"主/次/小趋势全面向下，{'成交量放大' if vol_confirm else '趋势下行'}"
        conf_val = 0.75
    elif score > 0.5:
        sig  = "buy"
        desc = f"主趋势向上，次/小趋势混合，整体偏多"
        conf_val = 0.5
    elif score < -0.5:
        sig  = "sell"
        desc = f"主趋势向下，整体偏空"
        conf_val = 0.5
    else:
        sig  = "neutral"
        desc = f"趋势分歧，主{primary} 次{secondary} 小{minor}"
        conf_val = 0.25

    return {
        "primary_trend":   primary,
        "secondary_trend": secondary,
        "minor_trend":     minor,
        "volume_confirms": vol_confirm,
        "score":           round(score, 2),
        "signal":          sig,
        "description":     desc,
        "confidence":      _conf(conf_val),
    }


# ===========================================================================
# P1 — 技术分析扩展
# ===========================================================================

# --- 6. 布林带(20, ±2σ) ---

def calc_bollinger(candles: list[dict], period: int = 20) -> dict:
    closes = [c["close"] for c in candles]
    if len(closes) < period:
        return {"error": "数据不足"}

    ma20  = _sma(closes, period)
    std20 = _stddev(closes, period)
    current = closes[-1]

    mid   = ma20[-1]
    std   = std20[-1]
    if mid is None or std is None:
        return {"error": "计算失败"}

    upper = round(mid + 2 * std, 2)  # type: ignore
    lower = round(mid - 2 * std, 2)  # type: ignore
    mid_r = round(mid, 2)            # type: ignore

    bandwidth = round((upper - lower) / mid_r * 100, 1) if mid_r > 0 else 0

    # 带宽收窄检测（近10日带宽 vs 近30日均带宽）
    bws = []
    for i in range(max(0, len(closes) - 40), len(closes)):
        if ma20[i] and std20[i]:
            bws.append((ma20[i] + 2 * std20[i] - (ma20[i] - 2 * std20[i])) / ma20[i] * 100)  # type: ignore
    squeeze = False
    if len(bws) >= 15:
        recent_bw = sum(bws[-10:]) / 10
        prior_bw  = sum(bws[-30:-10]) / max(len(bws[-30:-10]), 1)
        squeeze = recent_bw < prior_bw * 0.7

    # 价格位置
    if current > upper * 0.995:
        position, sig, desc = "upper", "sell", f"价格触及布林上轨 ${upper}，超买压力"
        conf_val = 0.55
    elif current < lower * 1.005:
        position, sig, desc = "lower", "buy", f"价格触及布林下轨 ${lower}，超卖反弹机会"
        conf_val = 0.55
    else:
        position = "middle"
        if squeeze:
            sig, desc = "watch", f"布林带收窄（带宽 {bandwidth}%），即将爆发性突破"
            conf_val = 0.5
        else:
            sig, desc = "neutral", f"价格在布林带中轨附近，带宽 {bandwidth}%"
            conf_val = 0.3

    return {
        "upper": upper,
        "middle": mid_r,
        "lower": lower,
        "bandwidth_pct": bandwidth,
        "squeeze": squeeze,
        "price_position": position,
        "signal": sig,
        "description": desc,
        "confidence": _conf(conf_val),
    }


# --- 7. 缺口识别 ---

def calc_gaps(candles: list[dict], lookback: int = 60) -> dict:
    recent = candles[-lookback:] if len(candles) >= lookback else candles
    closes  = [c["close"]  for c in candles]
    volumes = [c["volume"] for c in candles]
    avg_vol = sum(volumes[-20:]) / 20 if len(volumes) >= 20 else sum(volumes) / max(len(volumes), 1)

    gaps = []
    for i in range(1, len(recent)):
        prev_close = recent[i - 1]["close"]
        cur_open   = recent[i]["open"]
        gap_size   = cur_open - prev_close
        gap_pct    = abs(gap_size) / prev_close * 100 if prev_close > 0 else 0
        if gap_pct < 0.3:
            continue  # 太小的缺口忽略

        gap_dir = "up" if gap_size > 0 else "down"
        vol     = recent[i]["volume"]
        vol_ratio = vol / avg_vol

        # 是否已填补
        later_closes = [c["close"] for c in recent[i + 1:]]
        if gap_dir == "up":
            filled = any(c <= prev_close for c in later_closes)
        else:
            filled = any(c >= prev_close for c in later_closes)

        # 缺口类型判断（简化启发式）
        if vol_ratio > 1.8:
            gap_type = "breakaway"  # 突破缺口：放量 + 未填补倾向
        elif vol_ratio > 1.2 and not filled:
            gap_type = "runaway"    # 持续缺口：中等成交量
        elif vol_ratio > 2.0 and i >= len(recent) - 5:
            gap_type = "exhaustion" # 衰竭缺口：极大成交量 + 近期
        else:
            gap_type = "common"     # 普通缺口

        gaps.append({
            "date":       recent[i]["date"],
            "direction":  gap_dir,
            "gap_pct":    round(gap_pct, 2),
            "prev_close": round(prev_close, 2),
            "open":       round(cur_open, 2),
            "type":       gap_type,
            "filled":     filled,
            "vol_ratio":  round(vol_ratio, 2),
        })

    unfilled = [g for g in gaps if not g["filled"]]
    recent_gaps = gaps[-5:]

    sig = "neutral"
    desc = f"近60日发现 {len(gaps)} 个缺口，{len(unfilled)} 个未填补"
    if unfilled:
        latest_unfilled = unfilled[-1]
        if latest_unfilled["type"] == "breakaway":
            sig  = "buy" if latest_unfilled["direction"] == "up" else "sell"
            desc = f"突破缺口未填补（{latest_unfilled['date']}），{latest_unfilled['direction']} 方向动能强"

    return {
        "gaps": recent_gaps,
        "total_count": len(gaps),
        "unfilled_count": len(unfilled),
        "signal": sig,
        "description": desc,
        "confidence": "medium" if unfilled else "low",
    }


# --- 8. 自动趋势线 ---

def calc_trendline(candles: list[dict]) -> dict:
    if len(candles) < 20:
        return {"error": "数据不足"}

    sh, sl = _find_swing_points(candles, window=5)
    current = candles[-1]["close"]
    n = len(candles)

    def _fit_line(pts):
        """最小二乘拟合 y = a*x + b，返回 (a, b) 或 None"""
        if len(pts) < 2:
            return None
        xs = [float(p[1]) for p in pts]
        ys = [float(p[0]) for p in pts]
        x_mean = sum(xs) / len(xs)
        y_mean = sum(ys) / len(ys)
        denom = sum((x - x_mean) ** 2 for x in xs)
        if denom == 0:
            return None
        a = sum((xs[i] - x_mean) * (ys[i] - y_mean) for i in range(len(xs))) / denom
        b = y_mean - a * x_mean
        return (a, b)

    # 上升趋势线：连接摆动低点
    upline = None
    if len(sl) >= 2:
        params = _fit_line(sl[-5:])
        if params:
            a, b = params
            trend_val = a * (n - 1) + b
            # 判断是否被突破（当前价低于趋势线 1%）
            broken = current < trend_val * 0.99
            upline = {
                "slope": round(a, 4),
                "current_value": round(trend_val, 2),
                "distance_pct": round((current - trend_val) / trend_val * 100, 1) if trend_val > 0 else 0,
                "broken": broken,
                "touch_count": len(sl),
            }

    # 下降趋势线：连接摆动高点
    downline = None
    if len(sh) >= 2:
        params = _fit_line(sh[-5:])
        if params:
            a, b = params
            trend_val = a * (n - 1) + b
            broken = current > trend_val * 1.01
            downline = {
                "slope": round(a, 4),
                "current_value": round(trend_val, 2),
                "distance_pct": round((current - trend_val) / trend_val * 100, 1) if trend_val > 0 else 0,
                "broken": broken,
                "touch_count": len(sh),
            }

    sig  = "neutral"
    desc = "趋势线正常，无突破信号"
    conf_val = 0.3

    if downline and downline["broken"]:
        sig, desc, conf_val = "buy", f"价格向上突破下降趋势线（当前值 ${downline['current_value']}）", 0.65
    elif upline and upline["broken"]:
        sig, desc, conf_val = "sell", f"价格向下跌破上升趋势线（当前值 ${upline['current_value']}），趋势反转警告", 0.65

    return {
        "uptrend_line": upline,
        "downtrend_line": downline,
        "signal": sig,
        "description": desc,
        "confidence": _conf(conf_val),
    }


# --- 9. 量价四象限 ---

def calc_volume_price(candles: list[dict]) -> dict:
    if len(candles) < 20:
        return {"error": "数据不足"}

    volumes = [c["volume"] for c in candles]
    avg_vol = sum(volumes[-20:]) / 20

    labels = []
    for i in range(max(0, len(candles) - 7), len(candles)):
        c = candles[i]
        price_up = c["close"] > c["open"]
        vol_high = c["volume"] > avg_vol * 1.1

        if price_up and vol_high:
            label = "放量上涨"
            sig   = "bullish_strong"
        elif price_up and not vol_high:
            label = "缩量上涨"
            sig   = "bullish_weak"
        elif not price_up and vol_high:
            label = "放量下跌"
            sig   = "bearish_strong"
        else:
            label = "缩量下跌"
            sig   = "bearish_weak"

        labels.append({
            "date":   c["date"],
            "label":  label,
            "signal": sig,
            "close":  round(c["close"], 2),
            "vol_ratio": round(c["volume"] / avg_vol, 2),
        })

    # 连续同类型天数
    if labels:
        latest = labels[-1]["signal"]
        streak = 1
        for item in reversed(labels[:-1]):
            if item["signal"] == latest:
                streak += 1
            else:
                break

        # 综合信号
        recent3 = labels[-3:]
        bullish = sum(1 for l in recent3 if "bullish" in l["signal"])
        bearish = sum(1 for l in recent3 if "bearish" in l["signal"])
        if bullish >= 2:
            overall_sig, overall_desc = "buy", f"近3日多数放量/缩量规律偏多（{bullish}/3 日看涨）"
        elif bearish >= 2:
            overall_sig, overall_desc = "sell", f"近3日多数量价规律偏空（{bearish}/3 日看跌）"
        else:
            overall_sig, overall_desc = "neutral", "近3日量价信号混合"
    else:
        streak, latest, bullish, bearish = 1, "neutral", 0, 0
        overall_sig, overall_desc = "neutral", "数据不足"

    return {
        "daily_labels": labels,
        "avg_volume_20d": round(avg_vol),
        "latest_signal": latest,
        "streak_days": streak,
        "signal": overall_sig,
        "description": overall_desc,
        "confidence": "medium" if bullish >= 2 or bearish >= 2 else "low",
    }


# --- 10. 吹顶 / 卖出高潮 ---

def calc_extreme_emotion(candles: list[dict]) -> dict:
    if len(candles) < 10:
        return {"error": "数据不足"}

    volumes = [c["volume"] for c in candles]
    closes  = [c["close"]  for c in candles]
    avg_vol = sum(volumes[-20:]) / 20 if len(volumes) >= 20 else sum(volumes) / len(volumes)

    blowoff_date = None
    climax_date  = None

    # 扫描最近30根K线
    scan = candles[-30:] if len(candles) >= 30 else candles
    for i in range(2, len(scan)):
        prev3_closes = [scan[j]["close"] for j in range(max(0, i - 3), i)]
        prev3_up = all(prev3_closes[j] < prev3_closes[j + 1] for j in range(len(prev3_closes) - 1))

        c = scan[i]
        vol_extreme = c["volume"] > avg_vol * 1.8
        body = abs(c["close"] - c["open"])
        range_size = c["high"] - c["low"]
        big_candle = range_size > 0 and body / range_size > 0.6

        # 吹顶：连续上涨 + 极度放量长阳 + 次日收阴
        if prev3_up and vol_extreme and big_candle and c["close"] > c["open"]:
            if i + 1 < len(scan) and scan[i + 1]["close"] < scan[i + 1]["open"]:
                blowoff_date = c["date"]

        # 卖出高潮：连续下跌 + 放量长阴 + 次日反弹收阳
        prev3_down = all(prev3_closes[j] > prev3_closes[j + 1] for j in range(len(prev3_closes) - 1))
        if prev3_down and vol_extreme and big_candle and c["close"] < c["open"]:
            if i + 1 < len(scan) and scan[i + 1]["close"] > scan[i + 1]["open"]:
                climax_date = c["date"]

    sig, desc = "neutral", "近期无极端情绪信号"
    conf_val = 0.25
    if blowoff_date:
        sig, desc, conf_val = "sell", f"检测到吹顶信号（{blowoff_date}），极度放量后次日反转，警惕顶部", 0.7
    elif climax_date:
        sig, desc, conf_val = "buy", f"检测到卖出高潮（{climax_date}），恐慌性抛售后次日反弹，关注底部", 0.65

    return {
        "blowoff_top": blowoff_date,
        "selling_climax": climax_date,
        "signal": sig,
        "description": desc,
        "confidence": _conf(conf_val),
    }


# ===========================================================================
# P2 — 形态识别
# ===========================================================================

# --- 11. 头肩顶/底 ---

def calc_head_shoulders(candles: list[dict]) -> dict:
    sh, sl = _find_swing_points(candles, window=5)
    current = candles[-1]["close"]

    result = {
        "head_shoulders_top": None,
        "head_shoulders_bottom": None,
        "signal": "neutral",
        "description": "未检测到头肩形态",
        "confidence": "low",
    }

    # 头肩顶：最近3个摆动高点，中间最高
    if len(sh) >= 3:
        ls, head, rs = sh[-3], sh[-2], sh[-1]
        shoulder_diff = abs(ls[0] - rs[0]) / max(ls[0], rs[0])
        if head[0] > ls[0] and head[0] > rs[0] and shoulder_diff < 0.08:
            # 颈线
            neckline = min(
                candles[min(ls[1], head[1]):max(ls[1], head[1])]["close"]
                if False else  # placeholder
                min(ls[0], rs[0]) * 0.97,
                min(ls[0], rs[0])
            )
            target = neckline - (head[0] - neckline)
            result["head_shoulders_top"] = {
                "left_shoulder": round(ls[0], 2),
                "head": round(head[0], 2),
                "right_shoulder": round(rs[0], 2),
                "neckline": round(neckline, 2),
                "target": round(target, 2),
                "confirmed": current < neckline,
            }
            if current < neckline:
                result["signal"] = "sell"
                result["description"] = f"头肩顶颈线（{neckline:.2f}）跌破确认，目标 ${target:.2f}"
                result["confidence"] = "high"

    # 头肩底：最近3个摆动低点，中间最低
    if len(sl) >= 3:
        ls, head, rs = sl[-3], sl[-2], sl[-1]
        shoulder_diff = abs(ls[0] - rs[0]) / max(ls[0], rs[0])
        if head[0] < ls[0] and head[0] < rs[0] and shoulder_diff < 0.08:
            neckline = max(ls[0], rs[0]) * 1.02
            target = neckline + (neckline - head[0])
            result["head_shoulders_bottom"] = {
                "left_shoulder": round(ls[0], 2),
                "head": round(head[0], 2),
                "right_shoulder": round(rs[0], 2),
                "neckline": round(neckline, 2),
                "target": round(target, 2),
                "confirmed": current > neckline,
            }
            if current > neckline and result["signal"] == "neutral":
                result["signal"] = "buy"
                result["description"] = f"头肩底颈线（{neckline:.2f}）突破确认，目标 ${target:.2f}"
                result["confidence"] = "high"

    return result


# --- 12. 双顶(M顶) / 双底(W底) ---

def calc_double_top_bottom(candles: list[dict]) -> dict:
    sh, sl = _find_swing_points(candles, window=5)
    current = candles[-1]["close"]

    result = {
        "double_top": None,
        "double_bottom": None,
        "signal": "neutral",
        "description": "未检测到双顶/双底形态",
        "confidence": "low",
    }

    # 双顶：最近2个摆动高点高度差 <3%，中间回调 >5%
    if len(sh) >= 2:
        t1, t2 = sh[-2], sh[-1]
        height_diff = abs(t1[0] - t2[0]) / max(t1[0], t2[0])
        # 中间最低点
        between_lows = [c["low"] for c in candles[t1[1]:t2[1] + 1]]
        mid_low = min(between_lows) if between_lows else t1[0]
        pullback = (min(t1[0], t2[0]) - mid_low) / min(t1[0], t2[0])

        if height_diff < 0.03 and pullback > 0.05:
            neckline = round(mid_low, 2)
            target = round(neckline - (min(t1[0], t2[0]) - neckline), 2)
            result["double_top"] = {
                "top1": round(t1[0], 2), "top2": round(t2[0], 2),
                "neckline": neckline, "target": target,
                "confirmed": current < neckline,
            }
            if current < neckline:
                result["signal"] = "sell"
                result["description"] = f"双顶（M顶）颈线 ${neckline} 跌破，目标 ${target}"
                result["confidence"] = "medium"

    # 双底：最近2个摆动低点高度差 <3%，中间反弹 >5%
    if len(sl) >= 2:
        b1, b2 = sl[-2], sl[-1]
        height_diff = abs(b1[0] - b2[0]) / max(b1[0], b2[0])
        between_highs = [c["high"] for c in candles[b1[1]:b2[1] + 1]]
        mid_high = max(between_highs) if between_highs else b1[0]
        bounce = (mid_high - max(b1[0], b2[0])) / max(b1[0], b2[0])

        if height_diff < 0.03 and bounce > 0.05:
            neckline = round(mid_high, 2)
            target = round(neckline + (neckline - max(b1[0], b2[0])), 2)
            result["double_bottom"] = {
                "bottom1": round(b1[0], 2), "bottom2": round(b2[0], 2),
                "neckline": neckline, "target": target,
                "confirmed": current > neckline,
            }
            if current > neckline and result["signal"] == "neutral":
                result["signal"] = "buy"
                result["description"] = f"双底（W底）颈线 ${neckline} 突破，目标 ${target}"
                result["confidence"] = "medium"

    return result


# --- 13. 三角形形态 ---

def calc_triangle(candles: list[dict]) -> dict:
    if len(candles) < 20:
        return {"error": "数据不足"}

    recent = candles[-30:]
    highs  = [c["high"]  for c in recent]
    lows   = [c["low"]   for c in recent]

    # 简化：用最近几个摆动点检测收敛
    sh, sl = _find_swing_points(recent, window=3)

    result = {
        "triangle_type": None,
        "signal": "neutral",
        "description": "未检测到明显三角形形态",
        "confidence": "low",
    }

    if len(sh) >= 2 and len(sl) >= 2:
        high_slope = (sh[-1][0] - sh[-2][0]) / max(sh[-1][1] - sh[-2][1], 1)
        low_slope  = (sl[-1][0] - sl[-2][0]) / max(sl[-1][1] - sl[-2][1], 1)

        if high_slope < -0.02 and low_slope > 0.02:
            t_type = "symmetric"
            desc   = "对称三角形，等待突破方向确认"
        elif abs(high_slope) < 0.01 and low_slope > 0.02:
            t_type = "ascending"
            desc   = "上升三角形（看涨偏向），上轨水平下轨上扬"
        elif high_slope < -0.02 and abs(low_slope) < 0.01:
            t_type = "descending"
            desc   = "下降三角形（看跌偏向），上轨下行下轨水平"
        else:
            t_type = None
            desc   = "未检测到明显三角形"

        if t_type:
            result["triangle_type"] = t_type
            result["description"]   = desc
            result["confidence"]    = "medium"
            if t_type == "ascending":
                result["signal"] = "buy"
            elif t_type == "descending":
                result["signal"] = "sell"

    return result


# --- 14. 旗形 / 楔形 ---

def calc_flag_wedge(candles: list[dict]) -> dict:
    if len(candles) < 15:
        return {"error": "数据不足"}

    # 旗杆检测：最近10日内是否有连续4日以上超过1%单日涨跌
    pole_candles = candles[-15:-5]
    up_pole   = sum(1 for c in pole_candles if (c["close"] - c["open"]) / c["open"] > 0.01)
    down_pole = sum(1 for c in pole_candles if (c["open"] - c["close"]) / c["open"] > 0.01)

    flag_candles = candles[-5:]
    fh = [c["high"]  for c in flag_candles]
    fl = [c["low"]   for c in flag_candles]

    result = {
        "pattern": None,
        "signal": "neutral",
        "description": "未检测到旗形/楔形",
        "confidence": "low",
    }

    if up_pole >= 3:
        # 检测向下倾斜旗形
        flag_slope = (fh[-1] - fh[0]) / max(len(fh) - 1, 1)
        if flag_slope < 0:
            result.update({
                "pattern": "bull_flag",
                "signal": "buy",
                "description": "牛市旗形（强势上涨后向下整理），看涨延续",
                "confidence": "medium",
            })

    if down_pole >= 3:
        flag_slope = (fl[-1] - fl[0]) / max(len(fl) - 1, 1)
        if flag_slope > 0:
            result.update({
                "pattern": "bear_flag",
                "signal": "sell",
                "description": "熊市旗形（强势下跌后向上整理），看跌延续",
                "confidence": "medium",
            })

    # 楔形：上下轨同向收窄
    sh, sl = _find_swing_points(candles[-20:], window=3)
    if len(sh) >= 2 and len(sl) >= 2:
        high_slope = (sh[-1][0] - sh[-2][0]) / max(sh[-1][1] - sh[-2][1], 1)
        low_slope  = (sl[-1][0] - sl[-2][0]) / max(sl[-1][1] - sl[-2][1], 1)
        if high_slope > 0 and low_slope > 0 and high_slope < low_slope:
            result.update({
                "pattern": "rising_wedge",
                "signal": "sell",
                "description": "上升楔形（上下轨同步上扬但收窄），看跌反转",
                "confidence": "medium",
            })
        elif high_slope < 0 and low_slope < 0 and high_slope > low_slope:
            result.update({
                "pattern": "falling_wedge",
                "signal": "buy",
                "description": "下降楔形（上下轨同步下行但收窄），看涨反转",
                "confidence": "medium",
            })

    return result


# --- 15. Stochastic(5,3,3) ---

def calc_stochastic(candles: list[dict], k_period: int = 5, d_period: int = 3) -> dict:
    if len(candles) < k_period + d_period:
        return {"error": "数据不足"}

    closes = [c["close"] for c in candles]
    highs  = [c["high"]  for c in candles]
    lows   = [c["low"]   for c in candles]

    k_values = []
    for i in range(k_period - 1, len(candles)):
        h = max(highs[i - k_period + 1: i + 1])
        l = min(lows[i  - k_period + 1: i + 1])
        k = (closes[i] - l) / (h - l) * 100 if (h - l) > 0 else 50.0
        k_values.append(k)

    d_values = []
    for i in range(d_period - 1, len(k_values)):
        d_values.append(sum(k_values[i - d_period + 1: i + 1]) / d_period)

    if not d_values:
        return {"error": "数据不足"}

    current_k = round(k_values[-1], 1)
    current_d = round(d_values[-1], 1)

    # 金叉/死叉
    cross = "neutral"
    if len(k_values) > 1 and len(d_values) > 1:
        if k_values[-1] > d_values[-1] and k_values[-2] <= d_values[-2]:
            cross = "golden_cross"
        elif k_values[-1] < d_values[-1] and k_values[-2] >= d_values[-2]:
            cross = "death_cross"

    if current_k > 80 and cross == "death_cross":
        sig, desc = "sell", f"随机指标超买区（%K={current_k}）死叉，卖出信号"
        conf_val = 0.65
    elif current_k < 20 and cross == "golden_cross":
        sig, desc = "buy", f"随机指标超卖区（%K={current_k}）金叉，买入信号"
        conf_val = 0.65
    elif current_k > 80:
        sig, desc = "watch", f"随机指标超买（%K={current_k}），等待死叉确认"
        conf_val = 0.4
    elif current_k < 20:
        sig, desc = "watch", f"随机指标超卖（%K={current_k}），等待金叉确认"
        conf_val = 0.4
    else:
        sig, desc = "neutral", f"随机指标中性区间（%K={current_k}，%D={current_d}）"
        conf_val = 0.25

    return {
        "k": current_k,
        "d": current_d,
        "cross": cross,
        "signal": sig,
        "description": desc,
        "confidence": _conf(conf_val),
        "overbought": current_k > 80,
        "oversold": current_k < 20,
    }


# --- 16. Momentum / ROC ---

def calc_momentum(candles: list[dict], period: int = 14) -> dict:
    closes = [c["close"] for c in candles]
    if len(closes) < period + 1:
        return {"error": "数据不足"}

    momentum = closes[-1] - closes[-period - 1]
    roc      = (closes[-1] - closes[-period - 1]) / closes[-period - 1] * 100

    prev_momentum = closes[-2] - closes[-period - 2] if len(closes) > period + 1 else momentum
    zero_cross    = "bullish" if momentum > 0 and prev_momentum <= 0 else \
                    ("bearish" if momentum < 0 and prev_momentum >= 0 else "none")

    if zero_cross == "bullish":
        sig, desc = "buy", f"动量穿越零轴向上（ROC={roc:.1f}%），趋势转换信号"
        conf_val = 0.6
    elif zero_cross == "bearish":
        sig, desc = "sell", f"动量穿越零轴向下（ROC={roc:.1f}%），趋势转换信号"
        conf_val = 0.6
    elif momentum > 0:
        sig, desc = "neutral", f"正向动量（ROC={roc:.1f}%），趋势延续"
        conf_val = 0.3
    else:
        sig, desc = "neutral", f"负向动量（ROC={roc:.1f}%），下行动能持续"
        conf_val = 0.3

    return {
        "momentum": round(momentum, 2),
        "roc": round(roc, 2),
        "zero_cross": zero_cross,
        "signal": sig,
        "description": desc,
        "confidence": _conf(conf_val),
    }


# ===========================================================================
# P3 — 高级指标
# ===========================================================================

# --- 17. 三重顶/底 + 圆弧底 ---

def calc_triple_patterns(candles: list[dict]) -> dict:
    sh, sl = _find_swing_points(candles, window=5)
    current = candles[-1]["close"]

    result = {
        "triple_top": None, "triple_bottom": None, "rounding_bottom": None,
        "signal": "neutral", "description": "未检测到三重顶底/圆弧底",
        "confidence": "low",
    }

    if len(sh) >= 3:
        t1, t2, t3 = sh[-3], sh[-2], sh[-1]
        max_diff = max(abs(t1[0] - t2[0]), abs(t2[0] - t3[0]), abs(t1[0] - t3[0]))
        if max_diff / max(t1[0], t2[0], t3[0]) < 0.04:
            result["triple_top"] = {
                "tops": [round(t1[0], 2), round(t2[0], 2), round(t3[0], 2)],
                "avg": round((t1[0] + t2[0] + t3[0]) / 3, 2),
            }
            if current < min(t1[0], t3[0]) * 0.98:
                result["signal"] = "sell"
                result["description"] = "三重顶确认，可靠性高于双顶，看跌"
                result["confidence"] = "high"

    if len(sl) >= 3:
        b1, b2, b3 = sl[-3], sl[-2], sl[-1]
        max_diff = max(abs(b1[0] - b2[0]), abs(b2[0] - b3[0]), abs(b1[0] - b3[0]))
        if max_diff / max(b1[0], b2[0], b3[0]) < 0.04:
            result["triple_bottom"] = {
                "bottoms": [round(b1[0], 2), round(b2[0], 2), round(b3[0], 2)],
                "avg": round((b1[0] + b2[0] + b3[0]) / 3, 2),
            }
            if current > max(b1[0], b3[0]) * 1.02 and result["signal"] == "neutral":
                result["signal"] = "buy"
                result["description"] = "三重底确认，长期底部反转信号"
                result["confidence"] = "high"

    # 圆弧底：近60日收盘价标准差/均值 <5%，且最近价高于中间低点
    recent60 = candles[-60:] if len(candles) >= 60 else candles
    closes60 = [c["close"] for c in recent60]
    if len(closes60) >= 30:
        mean60 = sum(closes60) / len(closes60)
        std60  = statistics.stdev(closes60)
        mid_low = min(closes60[len(closes60)//4: 3*len(closes60)//4])
        if std60 / mean60 < 0.08 and closes60[-1] > mid_low * 1.03:
            result["rounding_bottom"] = {
                "period_days": len(closes60),
                "low_point": round(mid_low, 2),
                "current": round(closes60[-1], 2),
            }
            if result["signal"] == "neutral":
                result["signal"] = "buy"
                result["description"] = "圆弧底形态（价格缓慢U形），长期底部反转"
                result["confidence"] = "medium"

    return result


# --- 18. CCI ---

def calc_cci(candles: list[dict], period: int = 20) -> dict:
    if len(candles) < period:
        return {"error": "数据不足"}

    typical = [(c["high"] + c["low"] + c["close"]) / 3 for c in candles]
    ma = _sma(typical, period)

    cci_values = []
    for i in range(period - 1, len(typical)):
        if ma[i] is None:
            continue
        window = typical[i - period + 1: i + 1]
        mean_dev = sum(abs(v - ma[i]) for v in window) / period  # type: ignore
        cci = (typical[i] - ma[i]) / (0.015 * mean_dev) if mean_dev > 0 else 0  # type: ignore
        cci_values.append(cci)

    if not cci_values:
        return {"error": "计算失败"}

    current_cci = round(cci_values[-1], 1)

    if current_cci > 200:
        sig, desc = "sell", f"CCI {current_cci} 极端超买（>200），强烈超买警告"
        conf_val = 0.75
    elif current_cci > 100:
        sig, desc = "sell", f"CCI {current_cci} 超买（>100），短期回调风险"
        conf_val = 0.5
    elif current_cci < -200:
        sig, desc = "buy", f"CCI {current_cci} 极端超卖（<-200），强烈反弹信号"
        conf_val = 0.75
    elif current_cci < -100:
        sig, desc = "buy", f"CCI {current_cci} 超卖（<-100），关注反弹机会"
        conf_val = 0.5
    else:
        sig, desc = "neutral", f"CCI {current_cci} 正常区间（-100 ~ +100）"
        conf_val = 0.25

    return {
        "value": current_cci,
        "signal": sig,
        "description": desc,
        "confidence": _conf(conf_val),
    }


# --- 19. Parabolic SAR ---

def calc_parabolic_sar(candles: list[dict], af_init: float = 0.02, af_max: float = 0.20) -> dict:
    if len(candles) < 10:
        return {"error": "数据不足"}

    highs  = [c["high"]  for c in candles]
    lows   = [c["low"]   for c in candles]
    closes = [c["close"] for c in candles]

    # 初始化
    bull = closes[1] > closes[0]
    sar  = lows[0] if bull else highs[0]
    ep   = highs[0] if bull else lows[0]
    af   = af_init
    sar_values = [sar]
    trend_list = [bull]

    for i in range(1, len(candles)):
        if bull:
            sar = sar + af * (ep - sar)
            sar = min(sar, lows[i - 1], lows[max(0, i - 2)])
            if highs[i] > ep:
                ep = highs[i]
                af = min(af + af_init, af_max)
            if lows[i] < sar:
                bull, sar, ep, af = False, ep, lows[i], af_init
        else:
            sar = sar - af * (sar - ep)
            sar = max(sar, highs[i - 1], highs[max(0, i - 2)])
            if lows[i] < ep:
                ep = lows[i]
                af = min(af + af_init, af_max)
            if highs[i] > sar:
                bull, sar, ep, af = True, ep, highs[i], af_init
        sar_values.append(round(sar, 2))
        trend_list.append(bull)

    current_sar = sar_values[-1]
    is_bull     = trend_list[-1]
    distance_pct = round((closes[-1] - current_sar) / closes[-1] * 100, 1)

    if is_bull:
        sig  = "buy"
        desc = f"SAR 在价格下方 ${current_sar}（多头模式，动态止损 {distance_pct}%）"
    else:
        sig  = "sell"
        desc = f"SAR 在价格上方 ${current_sar}（空头模式），建议回避"

    # 翻转信号（最近一次趋势切换）
    flip_date = None
    for i in range(len(trend_list) - 1, 0, -1):
        if trend_list[i] != trend_list[i - 1]:
            flip_date = candles[i]["date"]
            break

    return {
        "sar": current_sar,
        "trend": "bullish" if is_bull else "bearish",
        "distance_pct": distance_pct,
        "last_flip_date": flip_date,
        "signal": sig,
        "description": desc,
        "confidence": "medium",
    }


# --- 20. 矩形整理（箱体）---

def calc_rectangle(candles: list[dict], lookback: int = 40) -> dict:
    recent = candles[-lookback:] if len(candles) >= lookback else candles
    highs  = [c["high"]  for c in recent]
    lows   = [c["low"]   for c in recent]
    closes = [c["close"] for c in candles]
    current = closes[-1]

    box_high = max(highs)
    box_low  = min(lows)
    box_height_pct = (box_high - box_low) / box_low * 100 if box_low > 0 else 0

    # 箱体有效性：价格在区间内振荡（最高-最低 / 中值 < 20%，且中间至少2次折返）
    mid = (box_high + box_low) / 2
    crosses = sum(1 for i in range(1, len(recent)) if
                  (recent[i]["close"] > mid) != (recent[i-1]["close"] > mid))

    in_box = box_low * 1.01 <= current <= box_high * 0.99

    result = {
        "box_high": round(box_high, 2),
        "box_low": round(box_low, 2),
        "box_height_pct": round(box_height_pct, 1),
        "mid": round(mid, 2),
        "oscillation_count": crosses,
        "in_box": in_box,
        "signal": "neutral",
        "description": f"箱体区间 ${box_low:.2f}~${box_high:.2f}（高度 {box_height_pct:.1f}%）",
        "confidence": "low",
    }

    if crosses >= 4 and in_box:
        result["signal"] = "watch"
        result["description"] = f"矩形整理中（{crosses} 次折返），等待突破方向"
        result["confidence"] = "medium"
    elif not in_box:
        if current > box_high:
            result["signal"] = "buy"
            result["description"] = f"价格向上突破箱体上轨 ${box_high:.2f}"
            result["confidence"] = "medium"
        else:
            result["signal"] = "sell"
            result["description"] = f"价格向下跌破箱体下轨 ${box_low:.2f}"
            result["confidence"] = "medium"

    return result


# ===========================================================================
# 综合函数：所有 P0 指标计算
# ===========================================================================

def calc_oscillators(symbol: str) -> dict:
    candles = _get_candles(symbol, 300)
    if not candles:
        return {"error": "无法获取数据"}
    return {
        "symbol": symbol,
        "rsi":        calc_rsi(candles),
        "macd":       calc_macd(candles),
        "stochastic": calc_stochastic(candles),
        "momentum":   calc_momentum(candles),
        "cci":        calc_cci(candles),
    }


def calc_trend_indicators(symbol: str) -> dict:
    candles = _get_candles(symbol, 300)
    if not candles:
        return {"error": "无法获取数据"}
    return {
        "symbol": symbol,
        "adx":         calc_adx(candles),
        "bollinger":   calc_bollinger(candles),
        "parabolic_sar": calc_parabolic_sar(candles),
        "trendline":   calc_trendline(candles),
        "fibonacci":   calc_fibonacci(candles),
        "dow_theory":  calc_dow_theory(candles),
    }


def calc_patterns(symbol: str) -> dict:
    candles = _get_candles(symbol, 300)
    if not candles:
        return {"error": "无法获取数据"}
    return {
        "symbol": symbol,
        "head_shoulders": calc_head_shoulders(candles),
        "double_top_bottom": calc_double_top_bottom(candles),
        "triangle":     calc_triangle(candles),
        "flag_wedge":   calc_flag_wedge(candles),
        "triple_patterns": calc_triple_patterns(candles),
        "rectangle":    calc_rectangle(candles),
    }


def calc_volume_signals(symbol: str) -> dict:
    candles = _get_candles(symbol, 300)
    if not candles:
        return {"error": "无法获取数据"}
    return {
        "symbol": symbol,
        "volume_price":    calc_volume_price(candles),
        "gaps":            calc_gaps(candles),
        "extreme_emotion": calc_extreme_emotion(candles),
    }


# ===========================================================================
# combined_signal(): 综合加权信号
# ===========================================================================

def combined_signal(symbol: str) -> dict:
    """
    综合所有指标，加权得出最终信号。
    权重：道氏趋势=3，ADX=2.5，RSI=1.5，MACD=1.5，形态=1，其余=0.5
    """
    candles = _get_candles(symbol, 300)
    if not candles:
        return {"error": "无法获取数据"}

    # 计算各模块
    rsi    = calc_rsi(candles)
    macd   = calc_macd(candles)
    adx    = calc_adx(candles)
    dow    = calc_dow_theory(candles)
    boll   = calc_bollinger(candles)
    sar    = calc_parabolic_sar(candles)
    mom    = calc_momentum(candles)
    cci    = calc_cci(candles)
    vp     = calc_volume_price(candles)
    ext    = calc_extreme_emotion(candles)
    hs     = calc_head_shoulders(candles)
    dt     = calc_double_top_bottom(candles)
    tri    = calc_triangle(candles)

    def _score(sig: str, weight: float) -> float:
        if sig == "buy":    return weight
        if sig == "sell":   return -weight
        if sig == "watch":  return 0.0
        return 0.0

    scores = [
        _score(dow.get("signal", "neutral"), 3.0),
        _score(adx.get("signal", "neutral"), 2.5),
        _score(rsi.get("signal", "neutral"), 1.5),
        _score(macd.get("signal", "neutral"), 1.5),
        _score(boll.get("signal", "neutral"), 1.0),
        _score(sar.get("signal", "neutral"), 1.0),
        _score(mom.get("signal", "neutral"), 0.8),
        _score(cci.get("signal", "neutral"), 0.8),
        _score(vp.get("signal", "neutral"), 0.7),
        _score(hs.get("signal", "neutral"), 1.0),
        _score(dt.get("signal", "neutral"), 1.0),
        _score(tri.get("signal", "neutral"), 0.7),
        _score(ext.get("signal", "neutral"), 1.5),
    ]

    total_weight = 3.0 + 2.5 + 1.5 + 1.5 + 1.0 + 1.0 + 0.8 + 0.8 + 0.7 + 1.0 + 1.0 + 0.7 + 1.5
    net_score = sum(scores) / total_weight  # -1 ~ +1

    # 背离降低置信度
    divergence_penalty = 0.0
    if rsi.get("divergence"):   divergence_penalty += 0.1
    if macd.get("divergence"):  divergence_penalty += 0.1

    # 海龟联动：海龟突破 + ADX>25 + RSI未超买
    from ta_engine import calc_turtle
    turtle = calc_turtle(symbol)
    turtle_valid = (
        turtle.get("recommendation") in ("买入", "试探买入") and
        adx.get("trending", False) and
        not rsi.get("overbought", False)
    )

    # 道氏主趋势 + ADX>25 + RSI未超买 + MACD金叉
    high_confidence_buy = (
        dow.get("primary_trend") == "Up" and
        adx.get("trending", False) and
        not rsi.get("overbought", False) and
        macd.get("cross") == "golden_cross"
    )

    if net_score > 0.3:
        sig  = "buy"
        desc = f"综合看涨（得分 {net_score:+.2f}），多数指标信号偏多"
    elif net_score < -0.3:
        sig  = "sell"
        desc = f"综合看跌（得分 {net_score:+.2f}），多数指标信号偏空"
    else:
        sig  = "neutral"
        desc = f"综合信号中性（得分 {net_score:+.2f}），观望"

    # 置信度
    abs_score = abs(net_score)
    if abs_score > 0.5:
        conf_val = 0.75 - divergence_penalty
    elif abs_score > 0.3:
        conf_val = 0.5 - divergence_penalty
    else:
        conf_val = 0.25

    # 特殊高置信度场景
    if high_confidence_buy:
        conf_val = max(conf_val, 0.8)
        desc += "（道氏+ADX+MACD金叉高置信度看涨）"
    if turtle_valid:
        desc += "（海龟突破+ADX有效）"

    return {
        "symbol": symbol,
        "net_score": round(net_score, 3),
        "signal": sig,
        "description": desc,
        "confidence": _conf(conf_val),
        "high_confidence_buy": high_confidence_buy,
        "turtle_valid_breakout": turtle_valid,
        "divergence_detected": bool(rsi.get("divergence") or macd.get("divergence")),
        "component_signals": {
            "dow_theory":   dow.get("signal"),
            "adx":          adx.get("signal"),
            "rsi":          rsi.get("signal"),
            "macd":         macd.get("signal"),
            "bollinger":    boll.get("signal"),
            "parabolic_sar": sar.get("signal"),
            "momentum":     mom.get("signal"),
            "cci":          cci.get("signal"),
            "volume_price": vp.get("signal"),
            "head_shoulders": hs.get("signal"),
            "double_patterns": dt.get("signal"),
            "triangle":     tri.get("signal"),
            "extreme":      ext.get("signal"),
        },
    }


def calc_indicators_summary() -> list[dict]:
    """10支标的全量信号摘要"""
    import time
    key = "indicators_summary"
    now = time.time()
    if key in _ind_cache and now - _ind_cache[key]["ts"] < _IND_TTL:
        return _ind_cache[key]["data"]

    symbols = ["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA",
               "META", "TSLA", "TSM", "QQQ", "SPY"]
    results = []
    for sym in symbols:
        try:
            cs = combined_signal(sym)
            candles = _get_candles(sym, 300)
            results.append({
                "symbol": sym,
                "price": round(candles[-1]["close"], 2) if candles else None,
                "combined": cs,
            })
        except Exception as e:
            results.append({"symbol": sym, "error": str(e)})

    _ind_cache[key] = {"data": results, "ts": now}
    return results
