"""QQQ 抄底信号 FULL_SYSTEM —— 5 个子信号实时监控。

子信号：
① VIX ≥ 40 —— 极度恐慌
② QQQ 3 年价格分位 ≤ 5% —— 历史低位
③ 距 52 周高点回撤 ≥ 20% —— 技术性熊市
④ 宽度枯竭 —— 近 60 日 ≥ 5 次 252 日新低，且最近 10 日未再创新低
⑤ VIX 持续恐慌后回落 —— VIX≥25 持续 20 日后首次 <25

历史回测：22 次触发，90.9% 胜率，1 年平均收益 +25.8%。
"""
import time
import datetime
import yfinance as yf
import pandas as pd

_cache: dict = {}
_TTL = 900  # 15 min


def _cached(key: str, fn):
    entry = _cache.get(key)
    if entry and time.time() - entry["ts"] < _TTL:
        return entry["data"]
    data = fn()
    if not data.get("error"):
        _cache[key] = {"ts": time.time(), "data": data}
    return data


def _percentile_of_score(series: pd.Series, value: float) -> float:
    """返回 value 在 series 中的百分位（0-100）。"""
    n = len(series)
    if n == 0:
        return 0.0
    count = (series <= value).sum()
    return float(count) / n * 100.0


def _compute() -> dict:
    try:
        # 拉 QQQ + VIX 日线 3 年（足够滚动 252/756 日窗口）
        qqq_df = yf.Ticker("QQQ").history(period="3y", interval="1d")
        vix_df = yf.Ticker("^VIX").history(period="3y", interval="1d")

        if qqq_df.empty or vix_df.empty:
            return {"error": "yfinance returned empty data", "signals": []}

        qqq_close = qqq_df["Close"].dropna()
        vix_close = vix_df["Close"].dropna()

        qqq_current = float(qqq_close.iloc[-1])
        vix_current = float(vix_close.iloc[-1])

        signals = []

        # ① VIX ≥ 40
        triggered_1 = vix_current >= 40
        signals.append({
            "id": "vix_extreme",
            "name": "VIX 极度恐慌",
            "condition": "VIX ≥ 40",
            "triggered": bool(triggered_1),
            "current_value": round(vix_current, 2),
            "threshold": 40,
            "progress_pct": round(min(100.0, vix_current / 40.0 * 100.0), 1),
            "distance_text": (
                f"已触发：VIX={vix_current:.1f}"
                if triggered_1
                else f"VIX={vix_current:.1f}，距离阈值还差 {40 - vix_current:.1f}"
            ),
        })

        # ② 3 年价格分位 ≤ 5%
        window_3y = qqq_close.tail(756)
        pct_3y = _percentile_of_score(window_3y, qqq_current)
        triggered_2 = pct_3y <= 5
        signals.append({
            "id": "percentile_3y",
            "name": "3 年价格分位 ≤ 5%",
            "condition": "QQQ 当前价格处于 3 年最低 5% 区间",
            "triggered": bool(triggered_2),
            "current_value": round(pct_3y, 1),
            "threshold": 5,
            # 分位越低越接近触发：用 (100 - pct) 做进度条，触发区 95%+
            "progress_pct": round(max(0.0, min(100.0, 100.0 - pct_3y)), 1),
            "distance_text": (
                f"已触发：当前处于 3 年 {pct_3y:.1f}% 分位"
                if triggered_2
                else f"当前 3 年 {pct_3y:.1f}% 分位，需降至 ≤5% 才触发"
            ),
        })

        # ③ 距 52 周高点回撤 ≥ 20%
        max_52w = float(qqq_close.tail(252).max())
        drawdown = (qqq_current / max_52w - 1.0) * 100.0  # 负数
        triggered_3 = drawdown <= -20
        # 进度：回撤 0 → 0%，回撤 -20% → 100%
        progress_3 = min(100.0, max(0.0, (-drawdown) / 20.0 * 100.0))
        signals.append({
            "id": "drawdown_52w",
            "name": "距 52 周高点回撤 ≥ 20%",
            "condition": "QQQ 从 52 周高点下跌 ≥ 20%",
            "triggered": bool(triggered_3),
            "current_value": round(drawdown, 2),
            "threshold": -20,
            "progress_pct": round(progress_3, 1),
            "distance_text": (
                f"已触发：当前回撤 {drawdown:.1f}%"
                if triggered_3
                else f"当前回撤 {drawdown:.1f}%，还需再跌 {abs(-20 - drawdown):.1f}% 才触发"
            ),
        })

        # ④ 宽度枯竭：近 60 日创 252 日新低 ≥ 5 次，且最近 10 日未再创新低
        rolling_min_252 = qqq_close.rolling(window=252, min_periods=252).min()
        is_new_low = (qqq_close == rolling_min_252) & rolling_min_252.notna()
        new_low_count_60 = int(is_new_low.tail(60).sum())
        last_10_no_new_low = int(is_new_low.tail(10).sum()) == 0
        triggered_4 = (new_low_count_60 >= 5) and last_10_no_new_low
        progress_4 = min(100.0, new_low_count_60 / 5.0 * 100.0)
        signals.append({
            "id": "breadth_exhaustion",
            "name": "宽度枯竭",
            "condition": "近 60 日 ≥ 5 次 252 日新低 且 最近 10 日无新低",
            "triggered": bool(triggered_4),
            "current_value": new_low_count_60,
            "threshold": 5,
            "progress_pct": round(progress_4, 1),
            "distance_text": (
                f"已触发：近 60 日共 {new_low_count_60} 次新低，最近 10 日已企稳"
                if triggered_4
                else (
                    f"近 60 日 {new_low_count_60} 次新低（需 ≥5）"
                    + ("，最近 10 日仍在创新低" if not last_10_no_new_low else "，等待至少 5 次新低")
                )
            ),
        })

        # ⑤ VIX 持续恐慌后回落：VIX≥25 持续 20 交易日后今日首次 <25
        if len(vix_close) >= 22:
            today_below = vix_current < 25
            yesterday_above = float(vix_close.iloc[-2]) >= 25
            # 倒数第 22 日到倒数第 3 日（共 20 日）全部 ≥ 25
            past_window = vix_close.iloc[-22:-2]
            past_20_persistence = bool((past_window >= 25).all()) and len(past_window) == 20
            triggered_5 = today_below and yesterday_above and past_20_persistence
            # 进度条：统计过去 22 日中 ≥25 的比例
            persistence_pct = float((vix_close.iloc[-22:] >= 25).sum()) / 22.0 * 100.0
        else:
            triggered_5 = False
            persistence_pct = 0.0
            today_below = vix_current < 25

        signals.append({
            "id": "vix_recovery",
            "name": "VIX 持续恐慌后回落",
            "condition": "VIX ≥ 25 持续 20 日后首次跌破 25",
            "triggered": bool(triggered_5),
            "current_value": round(vix_current, 2),
            "threshold": 25,
            "progress_pct": round(min(100.0, persistence_pct), 1),
            "distance_text": (
                f"已触发：VIX 从持续 ≥25 区间回落至 {vix_current:.1f}"
                if triggered_5
                else (
                    f"VIX={vix_current:.1f}（已 <25），但前 20 日未持续 ≥25"
                    if today_below
                    else f"VIX={vix_current:.1f}，需先进入 ≥25 持续 20 日区间"
                )
            ),
        })

        trigger_count = sum(1 for s in signals if s["triggered"])
        return {
            "error": None,
            "any_triggered": trigger_count > 0,
            "trigger_count": trigger_count,
            "total": len(signals),
            "signals": signals,
            "qqq_price": round(qqq_current, 2),
            "vix_value": round(vix_current, 2),
            "updated_at": datetime.datetime.utcnow().isoformat() + "Z",
        }
    except Exception as e:
        return {
            "error": str(e),
            "any_triggered": False,
            "trigger_count": 0,
            "total": 5,
            "signals": [],
        }


def compute_buy_signal() -> dict:
    """返回 FULL_SYSTEM 抄底信号状态（15 分钟内存缓存）。"""
    return _cached("buy_signal", _compute)
