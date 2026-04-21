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

def generate_signal(data: dict) -> dict:
    """
    五种操作场景判断，返回 {action, level, reason, zones, moat, trace}
    trace 是每一步判断过程，用于前端展示「分析过程」
    """
    sym = data["symbol"].replace(".US", "")
    moat = MOAT_RATINGS.get(sym, {"stars": 3, "reason": "未评级"})
    p200 = data["pct_vs_ma200"]
    p52  = data["pct_in_52w_range"]
    close = data["close"]
    ma200 = data["ma200"]
    ma50  = data["ma50"]

    # 分析链路：记录每个条件的判断结果
    trace = [
        {
            "label": "MA200 位置",
            "value": f"收盘 ${close} vs MA200 ${ma200}",
            "calc":  f"偏离 = ({close} - {ma200}) / {ma200} × 100 = {p200:+.1f}%",
            "pass":  p200 > 0,
            "flag":  "✅ 在 MA200 上方" if p200 > 0 else "❌ 在 MA200 下方",
        },
        {
            "label": "MA50 位置",
            "value": f"收盘 ${close} vs MA50 ${ma50}",
            "calc":  f"偏离 = {data['pct_vs_ma50']:+.1f}%",
            "pass":  data["pct_vs_ma50"] > 0,
            "flag":  "✅ 在 MA50 上方" if data["pct_vs_ma50"] > 0 else "❌ 在 MA50 下方",
        },
        {
            "label": "52周区间位置",
            "value": f"低位 ${data['low_52w']} ～ 高位 ${data['high_52w']}",
            "calc":  f"位置 = ({close} - {data['low_52w']}) / ({data['high_52w']} - {data['low_52w']}) × 100 = {p52:.1f}%",
            "pass":  20 <= p52 <= 80,
            "flag":  "🔴 高位区间 (>85%)" if p52 > 85 else ("🟢 低位区间 (<40%)" if p52 < 40 else "⚪ 中位区间"),
        },
        {
            "label": "护城河评级",
            "value": f"{moat['stars']} 星 / 5 星",
            "calc":  moat["reason"],
            "pass":  moat["stars"] >= 4,
            "flag":  "✅ 强护城河 (≥4星)" if moat["stars"] >= 4 else "⚠️ 护城河较弱 (<4星)",
        },
    ]

    # 情景一：高位减T仓
    if p52 > 90 and p200 > 8:
        scenario = "情景一：52周高位(>90%) 且 MA200溢价高(>8%) → 减T仓"
        return {
            "action": "减T仓",
            "level": "yellow",
            "emoji": "🟡",
            "reason": f"52周高位{p52:.0f}%，MA200溢价{p200:.0f}%，分批减仓控制安全边际",
            "zones": {"sell": round(close * 1.02, 2), "rebuy": round(ma200 * 1.02, 2)},
            "moat": moat,
            "scenario": scenario,
            "trace": trace,
        }

    # 情景二：跌破MA200，护城河强，等站稳
    if p200 < -5 and moat["stars"] >= 4:
        scenario = f"情景二：跌破MA200超过5%({p200:.1f}%) 且护城河强(≥4星) → 观察等待站稳"
        return {
            "action": "观察",
            "level": "red",
            "emoji": "🔴",
            "reason": f"跌破MA200 {abs(p200):.0f}%，等重新站稳再评估",
            "zones": {"watch": round(ma200, 2)},
            "moat": moat,
            "scenario": scenario,
            "trace": trace,
        }

    # 情景三：跌破MA200，护城河弱
    if p200 < -3 and moat["stars"] < 3:
        scenario = f"情景三：跌破MA200({p200:.1f}%) 且护城河弱(<3星) → 减仓"
        return {
            "action": "减仓",
            "level": "red",
            "emoji": "🔴",
            "reason": "弱势标的跌破MA200，护城河不足，优先减仓",
            "zones": {},
            "moat": moat,
            "scenario": scenario,
            "trace": trace,
        }

    # 情景四：低位恢复，性价比好
    if p52 < 40 and -5 <= p200 <= 5:
        scenario = f"情景四：52周低位区间({p52:.0f}%) 且 MA200附近(偏离{p200:+.1f}%) → 分批建仓"
        return {
            "action": "分批建仓",
            "level": "green",
            "emoji": "🟢",
            "reason": f"52周低位区间{p52:.0f}%，MA200附近，道没变，2-3-3-2分批建仓",
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
    scenario = f"情景五：不满足任何极端条件（52W位置{p52:.0f}%，MA200偏离{p200:+.1f}%）→ 底仓持有"
    return {
        "action": "底仓持有",
        "level": "neutral",
        "emoji": "⚪",
        "reason": "位置合理，底仓持有不动，等极端机会",
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
    """组合所有维度，返回完整分析结果"""
    signal = generate_signal(data)
    streak_dir, streak_days = calc_streak(candles or [])
    vol_signal = calc_volume_signal(candles or [])
    patterns = detect_candle_patterns(candles or [])

    # 势的标签
    势_tags = []
    if data["pct_vs_ma200"] > 0:
        势_tags.append("MA200上方 ✅")
    else:
        势_tags.append("MA200下方 ❌")
    if data["pct_in_52w_range"] > 90:
        势_tags.append("52W高位 ⚠️")
    elif data["pct_in_52w_range"] < 20:
        势_tags.append("52W低位 🟢")
    if streak_dir == "up" and streak_days >= 8:
        势_tags.append(f"连涨{streak_days}天 🔴极度过热")
    elif streak_dir == "down" and streak_days >= 5:
        势_tags.append(f"连跌{streak_days}天 🟢超卖")
    if vol_signal:
        势_tags.append("放量信号 ⚡")

    result = {
        **data,
        "signal": signal,
        "streak_dir": streak_dir,
        "streak_days": streak_days,
        "vol_signal": vol_signal,
        "candle_patterns": patterns,
        "势_tags": 势_tags,
    }

    if signal["action"] == "分批建仓":
        result["position_plan"] = build_position_plan(data["close"])

    return result
