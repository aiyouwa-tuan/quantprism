"""
Goal-Driven Trading OS — Stock Screener + AI Diagnosis
标的筛选 + AI 个股诊断（支撑位推演、趋势判定）
"""
import pandas as pd
import numpy as np
from dataclasses import dataclass, field
from market_data import fetch_stock_history, compute_technicals, fetch_current_price


# 板块分类
SECTORS = {
    "TECH": {
        "name": "科技",
        "symbols": ["AAPL", "MSFT", "GOOGL", "META", "AMZN", "NVDA", "TSLA", "CRM", "ADBE", "NFLX"],
    },
    "CHIP": {
        "name": "芯片",
        "symbols": ["NVDA", "AMD", "INTC", "TSM", "AVGO", "QCOM", "MU", "MRVL", "AMAT", "LRCX"],
    },
    "AUTO": {
        "name": "汽车",
        "symbols": ["TSLA", "GM", "F", "TM", "RIVN", "LCID", "NIO", "XPEV", "LI"],
    },
    "FINANCE": {
        "name": "金融",
        "symbols": ["JPM", "BAC", "GS", "MS", "WFC", "C", "BLK", "SCHW", "AXP", "V"],
    },
    "HEALTH": {
        "name": "医疗",
        "symbols": ["JNJ", "UNH", "PFE", "ABBV", "MRK", "LLY", "TMO", "ABT", "BMY", "AMGN"],
    },
    "ETF": {
        "name": "ETF",
        "symbols": ["SPY", "QQQ", "IWM", "DIA", "XLF", "XLK", "XLE", "XLV", "GLD", "TLT"],
    },
}


@dataclass
class StockDiagnosis:
    """AI 个股诊断结果"""
    symbol: str
    current_price: float
    # 趋势判定
    trend: str  # bullish / bearish / neutral
    trend_reason: str
    price_vs_ma200: float  # 当前价 vs MA200 百分比
    # 支撑位推演
    support_level: float
    support_method: str  # 推演方法说明
    safety_margin: float  # 安全边际百分比
    # 波动分析
    atr_14: float
    atr_pct: float  # ATR / 价格 百分比
    iv_rank: float  # 相对波动率排名 (0-100)
    # 关键指标
    rsi: float
    sma_20: float
    sma_50: float
    sma_200: float
    bb_position: str  # above_upper / near_upper / middle / near_lower / below_lower
    # 综合评分
    score: int  # 0-100
    recommendation: str
    # Sell Put 专用
    suggested_strike: float  # 建议行权价 (支撑位附近)
    suggested_dte: int  # 建议到期天数
    # 基本面字段 (来自 data_providers.fetch_fundamentals, 可选)
    pe_ratio: float = None
    eps: float = None
    market_cap: float = None
    analyst_rating: str = None
    analyst_target: float = None
    earnings_date: str = None
    sector: str = None
    beta: float = None


_diag_cache: dict = {}
_DIAG_CACHE_TTL = 1800  # 30 minutes


def diagnose_stock(symbol: str) -> StockDiagnosis:
    """
    AI 个股诊断：趋势 + 支撑位 + 波动率 + 综合评分

    推演逻辑（参考视频中的方法）：
    1. 趋势判定：股价 vs MA200
    2. 支撑基准：近半年最低点 或 MA200（取较高者）
    3. 波动校准：14日 ATR，扣除 1x ATR 作为波动冗余
    4. 最终支撑位 = 基准 - ATR
    5. 安全触发：如果支撑位距离现价 < 5%，强制回退至 10% 安全边际
    """
    # Check cache
    from datetime import datetime as _dt
    now = _dt.now().timestamp()
    if symbol in _diag_cache:
        cached_time, cached_result = _diag_cache[symbol]
        if now - cached_time < _DIAG_CACHE_TTL:
            return cached_result

    df = fetch_stock_history(symbol, period="1y")
    if df.empty or len(df) < 50:
        return _empty_diagnosis(symbol)

    df = compute_technicals(df)
    latest = df.iloc[-1]
    price = float(latest["close"])

    # 基本指标
    sma_20 = float(latest.get("sma_20", price))
    sma_50 = float(latest.get("sma_50", price))
    sma_200 = float(latest.get("sma_200", price))
    rsi = float(latest.get("rsi_14", 50))
    atr = float(latest.get("atr_14", price * 0.02))
    bb_upper = float(latest.get("bb_upper", price * 1.05))
    bb_lower = float(latest.get("bb_lower", price * 0.95))
    bb_mid = float(latest.get("bb_mid", price))

    # 1. 趋势判定
    price_vs_ma200 = (price - sma_200) / sma_200
    if price > sma_200 and price > sma_50:
        trend = "bullish"
        trend_reason = f"股价在 MA200 (${sma_200:.2f}) 和 MA50 (${sma_50:.2f}) 之上，上升趋势"
    elif price < sma_200:
        trend = "bearish"
        trend_reason = f"股价在 MA200 (${sma_200:.2f}) 之下，下降趋势"
    else:
        trend = "neutral"
        trend_reason = f"股价在 MA50 和 MA200 之间，震荡整理"

    # 2. 支撑位推演
    half_year = df.tail(126)  # 约半年
    half_year_low = float(half_year["low"].min())
    support_base = max(half_year_low, sma_200)  # 取较高者作为基准

    # 3. 波动校准：扣除 1x ATR
    support_level = support_base - atr

    # 4. 安全触发：支撑位距现价 < 5% 则强制回退
    safety_margin = (price - support_level) / price
    if safety_margin < 0.05:
        support_level = price * 0.90  # 强制 10% 安全边际
        safety_margin = 0.10
        support_method = f"安全触发：支撑过于激进，强制回退至 10% 安全边际 (${support_level:.2f})"
    else:
        support_method = (
            f"基准: ${support_base:.2f} (半年低点 ${half_year_low:.2f} vs MA200 ${sma_200:.2f} 取较高者)，"
            f"扣除 1x ATR (${atr:.2f}) = ${support_level:.2f}"
        )

    # 波动率分析
    atr_pct = atr / price
    returns = df["returns"].dropna()
    hist_vol = float(returns.std() * np.sqrt(252)) if len(returns) > 20 else 0.2
    # IV rank 简化：用历史波动率的百分位
    rolling_vol = returns.rolling(20).std() * np.sqrt(252)
    rolling_vol = rolling_vol.dropna()
    if len(rolling_vol) > 0:
        current_vol = float(rolling_vol.iloc[-1])
        iv_rank = float((rolling_vol < current_vol).mean() * 100)
    else:
        iv_rank = 50

    # BB 位置
    if price > bb_upper:
        bb_position = "above_upper"
    elif price > bb_mid + (bb_upper - bb_mid) * 0.5:
        bb_position = "near_upper"
    elif price < bb_lower:
        bb_position = "below_lower"
    elif price < bb_mid - (bb_mid - bb_lower) * 0.5:
        bb_position = "near_lower"
    else:
        bb_position = "middle"

    # 综合评分 (0-100, Sell Put 视角)
    score = 50
    # 趋势加分
    if trend == "bullish":
        score += 15
    elif trend == "bearish":
        score -= 20
    # 安全边际加分
    if safety_margin > 0.15:
        score += 15
    elif safety_margin > 0.10:
        score += 10
    elif safety_margin < 0.05:
        score -= 15
    # RSI (超卖 = 好的 Sell Put 时机)
    if rsi < 35:
        score += 10
    elif rsi > 70:
        score -= 10
    # IV rank (高 IV = 更多权利金)
    if iv_rank > 70:
        score += 10
    elif iv_rank < 30:
        score -= 5
    # BB 位置
    if bb_position in ("near_lower", "below_lower"):
        score += 5
    elif bb_position in ("near_upper", "above_upper"):
        score -= 5

    score = max(0, min(100, score))

    # 推荐
    if score >= 75:
        recommendation = "强烈推荐：趋势向上 + 安全边际充足 + 波动率适中"
    elif score >= 60:
        recommendation = "推荐：条件较好，可以考虑"
    elif score >= 40:
        recommendation = "中性：需要更多确认信号"
    else:
        recommendation = "不推荐：当前条件不利"

    # Sell Put 建议
    suggested_strike = round(support_level / 5) * 5  # 对齐到 $5
    suggested_dte = 30 if iv_rank > 50 else 45  # 高 IV 短期，低 IV 长期

    result = StockDiagnosis(
        symbol=symbol,
        current_price=round(price, 2),
        trend=trend,
        trend_reason=trend_reason,
        price_vs_ma200=round(price_vs_ma200, 4),
        support_level=round(support_level, 2),
        support_method=support_method,
        safety_margin=round(safety_margin, 4),
        atr_14=round(atr, 2),
        atr_pct=round(atr_pct, 4),
        iv_rank=round(iv_rank, 1),
        rsi=round(rsi, 1),
        sma_20=round(sma_20, 2),
        sma_50=round(sma_50, 2),
        sma_200=round(sma_200, 2),
        bb_position=bb_position,
        score=score,
        recommendation=recommendation,
        suggested_strike=suggested_strike,
        suggested_dte=suggested_dte,
    )
    _diag_cache[symbol] = (now, result)
    return result


def screen_sector(sector_key: str, min_score: int = 0) -> list[StockDiagnosis]:
    """筛选板块内所有标的并评分排序 (并行加速)"""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    sector = SECTORS.get(sector_key)
    if not sector:
        return []

    results = []
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {executor.submit(diagnose_stock, sym): sym for sym in sector["symbols"]}
        for future in as_completed(futures):
            try:
                diag = future.result()
                if diag.score >= min_score and diag.current_price > 0:
                    results.append(diag)
            except Exception:
                continue

    results.sort(key=lambda x: x.score, reverse=True)
    return results


def build_combo(diagnoses: list[StockDiagnosis], max_positions: int = 3, max_capital: float = 30000) -> dict:
    """
    构建 Sell Put 组合推荐

    选取评分最高的 N 只标的，计算组合预估收益
    """
    top = [d for d in diagnoses if d.score >= 50][:max_positions]
    if not top:
        return {"stocks": [], "total_capital": 0, "estimated_return": 0}

    combo_stocks = []
    total_capital = 0
    total_premium_est = 0

    for d in top:
        # 估算权利金（简化：ATR% * 安全边际 * 100）
        contracts = 1
        capital_per = d.suggested_strike * 100 * contracts  # 保证金估算
        premium_est = d.atr_14 * 0.3 * 100 * contracts  # 粗估权利金

        if total_capital + capital_per > max_capital:
            continue

        total_capital += capital_per
        total_premium_est += premium_est
        combo_stocks.append({
            "symbol": d.symbol,
            "score": d.score,
            "strike": d.suggested_strike,
            "dte": d.suggested_dte,
            "contracts": contracts,
            "capital": round(capital_per, 0),
            "premium_est": round(premium_est, 2),
            "support": d.support_level,
            "trend": d.trend,
        })

    est_return = total_premium_est / total_capital if total_capital > 0 else 0

    return {
        "stocks": combo_stocks,
        "total_capital": round(total_capital, 0),
        "total_premium": round(total_premium_est, 2),
        "estimated_return": round(est_return * 100, 2),
        "count": len(combo_stocks),
    }


def _empty_diagnosis(symbol: str) -> StockDiagnosis:
    return StockDiagnosis(
        symbol=symbol, current_price=0, trend="unknown", trend_reason="数据不足",
        price_vs_ma200=0, support_level=0, support_method="无", safety_margin=0,
        atr_14=0, atr_pct=0, iv_rank=0, rsi=0, sma_20=0, sma_50=0, sma_200=0,
        bb_position="unknown", score=0, recommendation="数据不足", suggested_strike=0, suggested_dte=30,
    )
