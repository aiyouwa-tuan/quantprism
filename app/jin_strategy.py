"""
金渐成方法论评分引擎
道 → 势 → 法 → 术 四层框架
"""
from __future__ import annotations
import math
from typing import Optional

# ---------------------------------------------------------------------------
# 法：护城河评级（人工维护）
# ---------------------------------------------------------------------------
MOAT_RATINGS: dict[str, dict] = {
    "NVDA": {"stars": 5, "reason": "AI训练芯片94%市占率，CUDA生态不可替代"},
    "TSM":  {"stars": 5, "reason": "高端芯片代工70%市占率，台积电工艺领先"},
    "GOOGL":{"stars": 5, "reason": "搜索92%市占率，YouTube+云三位一体"},
    "META": {"stars": 4, "reason": "社交+AI广告闭环，Zuckerberg执行力强"},
    "MSFT": {"stars": 4, "reason": "企业软件+Azure，纳德拉管理层优秀"},
    "AMZN": {"stars": 4, "reason": "AWS第一+电商护城河"},
    "AAPL": {"stars": 4, "reason": "消费电子生态，品牌溢价"},
    "TSLA": {"stars": 2, "reason": "马斯克精力分散，竞争格局恶化，不好把握"},
    "QQQ":  {"stars": 5, "reason": "纳指100一篮子第一，宽基首选"},
}

POSITION_TIERS = {
    "offensive": {
        "label": "进取型",
        "symbols": ["NVDA", "META", "GOOGL", "TSM"],
        "desc": "科技成长，博超额收益",
    },
    "balanced": {
        "label": "稳健型",
        "symbols": ["QQQ", "AMZN", "AAPL"],
        "desc": "宽基+消费，跟随市场Beta",
    },
    "defensive": {
        "label": "防守型",
        "symbols": ["MSFT"],
        "desc": "安全垫，现金流资产",
    },
}


# ---------------------------------------------------------------------------
# 术：K线形态检测
# ---------------------------------------------------------------------------

def is_hammer(candle: dict) -> bool:
    body = abs(candle["close"] - candle["open"])
    if body == 0:
        body = 0.001
    lower_shadow = min(candle["open"], candle["close"]) - candle["low"]
    upper_shadow = candle["high"] - max(candle["open"], candle["close"])
    return (lower_shadow >= 2 * body and upper_shadow <= 0.5 * body
            and candle["close"] > candle["open"])


def is_bullish_engulfing(prev: dict, curr: dict) -> bool:
    return (prev["close"] < prev["open"]
            and curr["close"] > curr["open"]
            and curr["open"] < prev["close"]
            and curr["close"] > prev["open"])


def is_shooting_star(candle: dict) -> bool:
    body = abs(candle["close"] - candle["open"])
    if body == 0:
        body = 0.001
    upper_shadow = candle["high"] - max(candle["open"], candle["close"])
    lower_shadow = min(candle["open"], candle["close"]) - candle["low"]
    return (upper_shadow >= 2 * body and lower_shadow <= 0.5 * body
            and candle["close"] < candle["open"])


def is_bearish_engulfing(prev: dict, curr: dict) -> bool:
    return (prev["close"] > prev["open"]
            and curr["close"] < curr["open"]
            and curr["open"] > prev["close"]
            and curr["close"] < prev["open"])


def detect_candle_patterns(candles: list[dict]) -> list[str]:
    """返回最近2根K线检测到的形态标签列表"""
    patterns = []
    if not candles:
        return patterns
    latest = candles[-1]
    prev = candles[-2] if len(candles) >= 2 else None

    if is_hammer(latest):
        patterns.append("锤子线")
    if is_shooting_star(latest):
        patterns.append("射击之星")
    if prev:
        if is_bullish_engulfing(prev, latest):
            patterns.append("吞没阳线")
        if is_bearish_engulfing(prev, latest):
            patterns.append("吞没阴线")
    return patterns


# ---------------------------------------------------------------------------
# 势：市场信号
# ---------------------------------------------------------------------------

def calc_streak(candles: list[dict]) -> tuple[str, int]:
    """计算当前连涨/连跌天数。返回 ('up'|'down', days)"""
    if len(candles) < 2:
        return ("up", 0)
    direction = None
    count = 0
    for i in range(len(candles) - 1, 0, -1):
        curr_up = candles[i]["close"] > candles[i - 1]["close"]
        d = "up" if curr_up else "down"
        if direction is None:
            direction = d
        if d == direction:
            count += 1
        else:
            break
    return (direction or "up", count)


def calc_volume_signal(candles: list[dict]) -> bool:
    """当日成交量是否 > 过去20日均量 × 1.5"""
    if len(candles) < 21:
        return False
    recent = candles[-20:]
    avg_vol = sum(c["volume"] for c in recent[:-1]) / 19
    return candles[-1]["volume"] > avg_vol * 1.5


# ---------------------------------------------------------------------------
# 主评分函数
# ---------------------------------------------------------------------------

def generate_signal(
    data: dict,
    streak_dir: str = "up",
    streak_days: int = 0,
    vol_signal: bool = False,
    candle_patterns: list | None = None,
) -> dict:
    """
    道势法术四层判断，返回操作信号 + 完整分析链路。

    势的高权重信号（连涨≥8天、连跌≥5天、放量）直接参与决策，
    术的K线形态在对应位置有效时强化信号。
    """
    candle_patterns = candle_patterns or []
    sym = data["symbol"].replace(".US", "")
    moat = MOAT_RATINGS.get(sym, {"stars": 3, "reason": "未评级"})
    p200 = data["pct_vs_ma200"]
    p52  = data["pct_in_52w_range"]
    close = data["close"]
    ma200 = data["ma200"]
    ma50  = data["ma50"]

    # ------------------------------------------------------------------
    # 势：所有信号，含权重和说明
    # ------------------------------------------------------------------
    streak_overheated = streak_dir == "up"  and streak_days >= 8
    streak_oversold   = streak_dir == "down" and streak_days >= 5
    bearish_pattern   = any(p in candle_patterns for p in ["射击之星", "吞没阴线"])
    bullish_pattern   = any(p in candle_patterns for p in ["锤子线", "吞没阳线"])

    shi_signals = []
    if p200 > 0:
        shi_signals.append({"text": f"MA200 上方 +{p200:.1f}%，大趋势向上", "weight": "高", "bullish": True})
    else:
        shi_signals.append({"text": f"MA200 下方 {p200:.1f}%，大趋势向下", "weight": "高", "bullish": False})
    if p52 > 90:
        shi_signals.append({"text": f"52周位置 {p52:.0f}%，接近历史高位，上涨空间有限", "weight": "中", "bullish": False})
    elif p52 < 20:
        shi_signals.append({"text": f"52周位置 {p52:.0f}%，处于历史低位，下跌空间有限", "weight": "中", "bullish": True})
    if streak_overheated:
        shi_signals.append({"text": f"连涨 {streak_days} 天，均值回归压力极大，短期高风险", "weight": "高", "bullish": False})
    if streak_oversold:
        shi_signals.append({"text": f"连跌 {streak_days} 天，短期超卖，注意企稳信号", "weight": "中", "bullish": True})
    if vol_signal:
        shi_signals.append({"text": "今日放量（>20日均量×1.5），主力资金活跃", "weight": "中", "bullish": None})

    # ------------------------------------------------------------------
    # 术：K线形态说明（加入上下文）
    # ------------------------------------------------------------------
    shu_signals = []
    for p in candle_patterns:
        if p == "锤子线":
            if p200 < 5:  # 在支撑位附近有效
                shu_signals.append({"pattern": p, "valid": True, "note": "在MA200支撑位出现锤子线，止跌信号有效，强化建仓信号"})
            else:
                shu_signals.append({"pattern": p, "valid": False, "note": "锤子线出现在高位，止跌意义弱"})
        elif p == "吞没阳线":
            if p52 < 50:  # 在低位出现有效
                shu_signals.append({"pattern": p, "valid": True, "note": "低位区间出现吞没阳线，反转信号有效"})
            else:
                shu_signals.append({"pattern": p, "valid": False, "note": "高位吞没阳线，可靠性较低"})
        elif p == "射击之星":
            if p52 > 70:  # 在高位出现有效
                shu_signals.append({"pattern": p, "valid": True, "note": "高位出现射击之星，见顶信号有效，强化减仓信号"})
            else:
                shu_signals.append({"pattern": p, "valid": False, "note": "射击之星出现在低位，见顶意义弱"})
        elif p == "吞没阴线":
            if p52 > 70:
                shu_signals.append({"pattern": p, "valid": True, "note": "高位出现吞没阴线，强烈反转信号，加速减仓"})
            else:
                shu_signals.append({"pattern": p, "valid": False, "note": "低位吞没阴线，可靠性较低"})

    # 有效的看涨/看跌K线形态
    valid_bearish_shu = any(s["valid"] for s in shu_signals if s["pattern"] in ["射击之星", "吞没阴线"])
    valid_bullish_shu = any(s["valid"] for s in shu_signals if s["pattern"] in ["锤子线", "吞没阳线"])

    # ------------------------------------------------------------------
    # 道势法术 trace（展示用）
    # ------------------------------------------------------------------
    trace = {
        "dao": {"text": "美股科技 ✅", "note": "规则透明，信息充分，AI不可逆，长期确定性高"},
        "shi": shi_signals,
        "fa":  {"stars": moat["stars"], "reason": moat["reason"]},
        "shu": shu_signals if shu_signals else [{"pattern": "无典型形态", "valid": None, "note": "最近2根K线无锤子线/吞没/射击之星形态"}],
    }

    # ------------------------------------------------------------------
    # 五种操作场景（势+术联合判断）
    # ------------------------------------------------------------------

    # 情景一：高位减T仓
    # 触发条件：52W高位>90% 且 MA200溢价>8%
    # 加强条件：连涨≥8天（极度过热）或 有效空头K线形态
    if p52 > 90 and p200 > 8:
        urgency = "高" if (streak_overheated or valid_bearish_shu) else "中"
        extra = []
        if streak_overheated:
            extra.append(f"叠加连涨{streak_days}天过热信号")
        if valid_bearish_shu:
            extra.append("叠加有效空头K线形态")
        extra_str = "（" + "、".join(extra) + "，紧迫程度升高）" if extra else ""
        scenario = f"势：52W高位{p52:.0f}% + MA200溢价{p200:.0f}%{extra_str} → 减T仓（紧迫度：{urgency}）"
        sell_target  = round(close * 1.02, 2)
        rebuy_target = round(ma200 * 1.02, 2)
        expected_gain = round((sell_target - rebuy_target) / rebuy_target * 100, 1)
        return {
            "action": "减T仓" if urgency == "中" else "立即减T仓",
            "level": "yellow",
            "emoji": "🟡",
            "urgency": urgency,
            "reason": f"52周高位{p52:.0f}%，MA200溢价{p200:.0f}%{extra_str}",
            "zones": {"sell": sell_target, "rebuy": rebuy_target},
            "operation": {
                "what":   "卖出 T仓部分（约总仓位的 30-40%），保留底仓不动",
                "when":   "当前价格附近或反弹时分批卖出，不要追跌卖",
                "sell_at": sell_target,
                "sell_note": f"目标卖出价（当前 ${close} × 1.02），有强势反弹时挂单",
                "rebuy_at": rebuy_target,
                "rebuy_note": f"回购价（MA200 × 1.02 = ${rebuy_target}），等回调至此再建回 T仓",
                "t_gain_pct": expected_gain,
                "t_gain_note": f"T仓操作预期差价收益约 {expected_gain}%",
                "keep": "底仓（约总仓位 50-60%）全程持有，不参与 T 操作",
            },
            "moat": moat,
            "scenario": scenario,
            "trace": trace,
        }

    # 情景二：跌破MA200，护城河强
    # 加强条件：连跌≥5天（超卖）→ 降低仓位要求，准备等待
    if p200 < -5 and moat["stars"] >= 4:
        oversold_note = f"连跌{streak_days}天已超卖，企稳信号可能临近，更接近买点" if streak_oversold else ""
        scenario = f"势：跌破MA200 {abs(p200):.1f}% + 法：护城河强{moat['stars']}星 → 观察"
        if streak_oversold:
            scenario += f"（连跌{streak_days}天超卖，企稳后可考虑建仓）"
        return {
            "action": "观察",
            "level": "red",
            "emoji": "🔴",
            "urgency": "中",
            "reason": f"跌破MA200 {abs(p200):.0f}%，等重新站稳再评估。{oversold_note}",
            "zones": {"watch": round(ma200, 2)},
            "moat": moat,
            "scenario": scenario,
            "trace": trace,
        }

    # 情景三：跌破MA200，护城河弱
    # 加强条件：有效空头K线形态 → 加速减仓
    if p200 < -3 and moat["stars"] < 3:
        accel = "，叠加有效空头形态，加速减仓" if valid_bearish_shu else ""
        scenario = f"势：跌破MA200 {abs(p200):.1f}% + 法：护城河弱{moat['stars']}星{accel} → 减仓"
        return {
            "action": "减仓",
            "level": "red",
            "emoji": "🔴",
            "urgency": "高" if valid_bearish_shu else "中",
            "reason": f"弱势标的跌破MA200，护城河不足{accel}，优先减仓",
            "zones": {},
            "moat": moat,
            "scenario": scenario,
            "trace": trace,
        }

    # 情景四：低位恢复，分批建仓
    # 强化条件：有效多头K线形态 → 增加信心，可提高第一批仓位
    if p52 < 40 and -5 <= p200 <= 5:
        confirm = "，叠加有效多头K线形态，信号可靠性提高" if valid_bullish_shu else ""
        scenario = f"势：52W低位{p52:.0f}% + MA200附近{p200:+.1f}%{confirm} → 分批建仓"
        return {
            "action": "分批建仓",
            "level": "green",
            "emoji": "🟢",
            "urgency": "中",
            "reason": f"52周低位区间{p52:.0f}%，MA200附近，道没变，2-3-3-2分批建仓{confirm}",
            "zones": {
                "buy1": round(close * 0.97, 2),
                "buy2": round(close * 0.93, 2),
                "buy3": round(close * 0.88, 2),
            },
            "moat": moat,
            "scenario": scenario,
            "trace": trace,
        }

    # 情景五：合理区间，持有
    # 注意：如果连涨过热，提示减T仓警戒
    note = ""
    if streak_overheated:
        note = f"⚠️ 虽未达高位极值，但已连涨{streak_days}天，注意均值回归风险"
    scenario = f"势：52W位置{p52:.0f}%，MA200偏离{p200:+.1f}%，无极端信号 → 底仓持有"
    return {
        "action": "底仓持有",
        "level": "neutral",
        "emoji": "⚪",
        "urgency": "低",
        "reason": f"位置合理，底仓持有不动，等极端机会。{note}",
        "zones": {"add": round(ma200 * 1.02, 2)},
        "moat": moat,
        "scenario": scenario,
        "trace": trace,
    }


def build_position_plan(base_price: float) -> list[dict]:
    return [
        {"batch": 1, "pct": 20, "price": round(base_price, 2),            "label": "斥候仓，先探路"},
        {"batch": 2, "pct": 30, "price": round(base_price * 0.95, 2),     "label": "确认上行趋势"},
        {"batch": 3, "pct": 30, "price": round(base_price * 0.90, 2),     "label": "上行势头猛时追加"},
        {"batch": 4, "pct": 20, "price": round(base_price * 0.85, 2),     "label": "调整结束再加最后一批"},
    ]


def analyze_stock(data: dict, candles: list[dict] | None = None) -> dict:
    """道势法术四层联合分析，势/术信号真正参与决策"""
    candles = candles or []
    streak_dir, streak_days = calc_streak(candles)
    vol_signal = calc_volume_signal(candles)
    patterns = detect_candle_patterns(candles)

    # 势/术信号传入 generate_signal，真正影响结论
    signal = generate_signal(
        data,
        streak_dir=streak_dir,
        streak_days=streak_days,
        vol_signal=vol_signal,
        candle_patterns=patterns,
    )

    result = {
        **data,
        "signal": signal,
        "streak_dir": streak_dir,
        "streak_days": streak_days,
        "vol_signal": vol_signal,
        "candle_patterns": patterns,
    }

    if signal["action"] in ("分批建仓",):
        result["position_plan"] = build_position_plan(data["close"])

    return result
