"""
Goal-Driven Trading OS — AI 策略研究员
根据用户要求搜索、解析、回测、验证策略
"""
import os
import math
import logging

logger = logging.getLogger(__name__)


# ─── AI 调用（复用 ai_analysis 的配置）─────────────────────────────────────────

def _get_ai_key_and_provider():
    """检测可用 AI provider（env 变量方式）"""
    from ai_analysis import AI_PROVIDERS, get_active_provider
    provider = get_active_provider()
    if not provider:
        return None, None
    cfg = AI_PROVIDERS[provider]
    key = os.getenv(cfg["env_key"])
    return provider, key


def _call_ai(prompt: str, max_tokens: int = 1500) -> str | None:
    """调用当前可用 AI 返回文本"""
    from ai_analysis import AI_PROVIDERS, get_active_provider, _call_openai_compatible, _call_claude, _call_gemini
    provider = get_active_provider()
    if not provider:
        return None
    cfg = AI_PROVIDERS[provider]
    key = os.getenv(cfg["env_key"])
    try:
        if provider in ("deepseek", "openai"):
            result = _call_openai_compatible(cfg["base_url"], key, cfg["model"], prompt, provider)
        elif provider == "claude":
            result = _call_claude(key, cfg["model"], prompt)
        elif provider == "gemini":
            result = _call_gemini(key, cfg["model"], prompt)
        else:
            return None
        return result.get("analysis")
    except Exception as e:
        logger.warning(f"AI call failed: {e}")
        return None


# ─── 回测引擎 ─────────────────────────────────────────────────────────────────

def backtest_strategy(strategy: dict, symbol: str = "SPY", years: int = 2) -> dict:
    """
    用历史数据对策略做简单回测。

    对以下类型实现真实逻辑：
    - stock：基于 SMA/RSI/布林带的入场规则
    - sell_put：用 ATR 估算权利金，模拟 Theta 收益
    - covered_call：在持股基础上每月卖 Call
    - call/put：基于方向动量的买入期权 P&L

    返回: { win_rate, annual_return, max_drawdown, num_trades, sharpe_ratio }
    """
    try:
        from market_data import fetch_stock_history, compute_technicals
    except ImportError:
        return _empty_backtest()

    period = f"{years}y"
    df = fetch_stock_history(symbol, period=period)
    if df is None or df.empty or len(df) < 60:
        return _empty_backtest()

    df = compute_technicals(df)
    instrument = strategy.get("instrument", "stock")
    style = strategy.get("style", "momentum")
    params = strategy.get("params", {})

    if instrument == "stock":
        return _backtest_stock(df, params, style, years)
    elif instrument == "sell_put":
        return _backtest_sell_put(df, params, years)
    elif instrument == "covered_call":
        return _backtest_covered_call(df, params, years)
    elif instrument in ("call", "put"):
        return _backtest_directional_option(df, params, instrument, years)
    else:
        return _backtest_stock(df, params, style, years)


def _empty_backtest():
    return {
        "win_rate": 0.0,
        "annual_return": 0.0,
        "max_drawdown": 0.0,
        "num_trades": 0,
        "sharpe_ratio": 0.0,
        "error": "insufficient data",
    }


def _backtest_stock(df, params: dict, style: str, years: int) -> dict:
    """正股买入/卖出回测"""
    import numpy as np

    close = df["close"].values
    sma20 = df.get("sma_20", df["close"]).values
    sma50 = df.get("sma_50", df["close"]).values
    sma200 = df.get("sma_200", df["close"]).bfill().values
    rsi = df.get("rsi_14", df["close"]).values
    bb_lower = df.get("bb_lower", df["close"]).values
    bb_mid = df.get("bb_mid", df["close"]).values

    stop_loss_pct = params.get("stop_loss_pct", -0.08)
    profit_pct = params.get("profit_target", 0.15)

    trades = []
    in_trade = False
    entry_price = 0.0

    for i in range(50, len(close)):
        c = close[i]
        if math.isnan(c):
            continue

        if not in_trade:
            # Entry logic depends on style
            signal = False
            if style == "momentum":
                # Buy when SMA20 > SMA50 and price > SMA200
                if (not math.isnan(sma20[i]) and not math.isnan(sma50[i]) and not math.isnan(sma200[i])
                        and sma20[i] > sma50[i] and c > sma200[i]):
                    signal = True
            elif style == "mean_reversion":
                # RSI oversold below 35 and price near BB lower
                if (not math.isnan(rsi[i]) and not math.isnan(bb_lower[i])
                        and rsi[i] < 35 and c < bb_lower[i] * 1.02):
                    signal = True
            else:
                # Default: price above SMA200
                if not math.isnan(sma200[i]) and c > sma200[i]:
                    signal = True

            if signal:
                in_trade = True
                entry_price = c
        else:
            pnl_pct = (c - entry_price) / entry_price
            # Exit: stop loss or profit target or SMA200 breakdown
            exit_signal = False
            if pnl_pct <= stop_loss_pct:
                exit_signal = True
            elif pnl_pct >= profit_pct:
                exit_signal = True
            elif style == "mean_reversion" and not math.isnan(bb_mid[i]) and c > bb_mid[i]:
                exit_signal = True  # revert to mean
            elif style == "momentum" and not math.isnan(sma20[i]) and not math.isnan(sma50[i]) and sma20[i] < sma50[i]:
                exit_signal = True  # crossover reversal

            if exit_signal:
                trades.append(pnl_pct)
                in_trade = False

    if not trades:
        return _empty_backtest()

    trades_arr = np.array(trades)
    win_rate = float(np.mean(trades_arr > 0))
    avg_return = float(np.mean(trades_arr))
    num_trades = len(trades)
    # Annualize: assume avg trade lasts ~15-30 days
    trades_per_year = 252 / max(len(close) / max(num_trades, 1), 1)
    annual_return = (1 + avg_return) ** min(trades_per_year, 20) - 1

    # Max drawdown via equity curve
    equity = np.cumprod(1 + trades_arr)
    running_max = np.maximum.accumulate(equity)
    drawdown = (equity - running_max) / running_max
    max_drawdown = float(abs(drawdown.min()))

    # Sharpe (simplified, annualized)
    std = float(np.std(trades_arr))
    sharpe = (avg_return / std * math.sqrt(252 / max(len(close) / max(num_trades, 1), 1))) if std > 0 else 0.0

    return {
        "win_rate": round(win_rate * 100, 1),
        "annual_return": round(annual_return * 100, 1),
        "max_drawdown": round(max_drawdown * 100, 1),
        "num_trades": num_trades,
        "sharpe_ratio": round(sharpe, 2),
    }


def _backtest_sell_put(df, params: dict, years: int) -> dict:
    """
    卖 Put 回测：用 ATR 估算 Put 权利金，每月循环

    假设：
    - 每30天滚动卖一次 Put（delta 0.25-0.30 虚值）
    - 权利金 ≈ ATR * delta * 合理溢价系数
    - 止盈50%权利金，止损200%权利金
    """
    import numpy as np

    close = df["close"].values
    atr = df.get("atr_14", df["close"] * 0.02).bfill().values

    profit_target = params.get("profit_target", 0.5)
    stop_loss_mult = abs(params.get("stop_loss_pct", -2.0))
    delta = params.get("delta_target", 0.25)
    dte = params.get("dte_min", 30)

    trades = []
    i = 50
    while i < len(close) - dte:
        c = close[i]
        atr_val = atr[i] if not math.isnan(atr[i]) else c * 0.02

        # Estimate Put premium: ATR * delta * sqrt(dte/252) * IV_multiplier
        iv_multiplier = 1.3  # typical IV premium over realized vol
        premium_pct = (atr_val / c) * delta * math.sqrt(dte / 252) * iv_multiplier * 100
        premium_pct = max(min(premium_pct, 5.0), 0.3)  # cap between 0.3% - 5%

        # Simulate next dte days
        end_idx = min(i + dte, len(close) - 1)
        prices_in_window = close[i:end_idx + 1]
        min_price = float(np.min(prices_in_window))
        end_price = close[end_idx]

        strike = c * (1 - delta * 0.3)  # approximate OTM strike
        put_intrinsic = max(strike - end_price, 0)
        put_intrinsic_pct = put_intrinsic / c * 100

        if put_intrinsic_pct <= premium_pct * profit_target:
            # Win: keep profit_target * premium
            trade_return = premium_pct * profit_target / 100
        elif put_intrinsic_pct >= premium_pct * stop_loss_mult:
            # Stop out
            trade_return = -premium_pct * stop_loss_mult / 100
        else:
            # Hold to expiry
            trade_return = (premium_pct - put_intrinsic_pct) / 100

        trades.append(trade_return)
        i += dte  # next trade after expiry

    if not trades:
        return _empty_backtest()

    trades_arr = np.array(trades)
    win_rate = float(np.mean(trades_arr > 0))
    avg_return = float(np.mean(trades_arr))
    trades_per_year = 252 / dte
    annual_return = (1 + avg_return) ** trades_per_year - 1

    equity = np.cumprod(1 + trades_arr)
    running_max = np.maximum.accumulate(equity)
    drawdown = (equity - running_max) / running_max
    max_drawdown = float(abs(drawdown.min()))

    std = float(np.std(trades_arr))
    sharpe = (avg_return * trades_per_year) / (std * math.sqrt(trades_per_year)) if std > 0 else 0.0

    return {
        "win_rate": round(win_rate * 100, 1),
        "annual_return": round(annual_return * 100, 1),
        "max_drawdown": round(max_drawdown * 100, 1),
        "num_trades": len(trades),
        "sharpe_ratio": round(sharpe, 2),
    }


def _backtest_covered_call(df, params: dict, years: int) -> dict:
    """
    Covered Call 回测：持有100股 + 每月卖 Call
    月收益 = 股价涨跌 + Call 权利金（若未行权）
    """
    import numpy as np

    close = df["close"].values
    atr = df.get("atr_14", df["close"] * 0.01).bfill().values

    delta = params.get("delta_target", 0.3)
    dte = params.get("dte_min", 30)
    profit_target = params.get("profit_target", 0.5)

    trades = []
    i = 50
    while i < len(close) - dte:
        c = close[i]
        atr_val = atr[i] if not math.isnan(atr[i]) else c * 0.01

        # Call premium estimate
        iv_multiplier = 1.2
        call_premium_pct = (atr_val / c) * delta * math.sqrt(dte / 252) * iv_multiplier * 100
        call_premium_pct = max(min(call_premium_pct, 4.0), 0.2)

        end_idx = min(i + dte, len(close) - 1)
        end_price = close[end_idx]
        stock_return = (end_price - c) / c

        # If stock rose above strike (delta * c above), Call gets called away
        strike = c * (1 + (1 - delta) * 0.05)
        if end_price > strike:
            # Called away: capped at strike + premium
            trade_return = (strike - c) / c + call_premium_pct / 100
        else:
            # Keep stock + keep premium
            trade_return = stock_return + call_premium_pct / 100

        trades.append(trade_return)
        i += dte

    if not trades:
        return _empty_backtest()

    trades_arr = np.array(trades)
    win_rate = float(np.mean(trades_arr > 0))
    avg_return = float(np.mean(trades_arr))
    trades_per_year = 252 / dte
    annual_return = (1 + avg_return) ** trades_per_year - 1

    equity = np.cumprod(1 + trades_arr)
    running_max = np.maximum.accumulate(equity)
    drawdown = (equity - running_max) / running_max
    max_drawdown = float(abs(drawdown.min()))

    std = float(np.std(trades_arr))
    sharpe = (avg_return * trades_per_year) / (std * math.sqrt(trades_per_year)) if std > 0 else 0.0

    return {
        "win_rate": round(win_rate * 100, 1),
        "annual_return": round(annual_return * 100, 1),
        "max_drawdown": round(max_drawdown * 100, 1),
        "num_trades": len(trades),
        "sharpe_ratio": round(sharpe, 2),
    }


def _backtest_directional_option(df, params: dict, option_type: str, years: int) -> dict:
    """
    方向性期权（买 Call / 买 Put）回测
    用 ATR 估算权利金成本，基于价格方向判断盈亏
    """
    import numpy as np

    close = df["close"].values
    sma20 = df.get("sma_20", df["close"]).values
    sma50 = df.get("sma_50", df["close"]).values
    rsi = df.get("rsi_14", df["close"]).values
    atr = df.get("atr_14", df["close"] * 0.02).bfill().values

    delta = params.get("delta_target", 0.5)
    dte = params.get("dte_min", 30)
    profit_target = params.get("profit_target", 0.5)
    stop_loss = abs(params.get("stop_loss_pct", -0.5))

    trades = []
    i = 50
    while i < len(close) - dte:
        c = close[i]
        atr_val = atr[i] if not math.isnan(atr[i]) else c * 0.02

        # Entry signal
        signal = False
        if option_type == "call" and not math.isnan(sma20[i]) and not math.isnan(sma50[i]):
            signal = sma20[i] > sma50[i] and (math.isnan(rsi[i]) or rsi[i] > 50)
        elif option_type == "put" and not math.isnan(sma20[i]) and not math.isnan(sma50[i]):
            signal = sma20[i] < sma50[i] and (math.isnan(rsi[i]) or rsi[i] < 50)

        if signal:
            # Option cost ≈ ATR * delta * sqrt(dte/252) * leverage
            option_cost_pct = (atr_val / c) * delta * math.sqrt(dte / 252) * 1.2
            option_cost_pct = max(min(option_cost_pct, 0.10), 0.01)

            end_idx = min(i + dte, len(close) - 1)
            end_price = close[end_idx]

            if option_type == "call":
                underlying_move = (end_price - c) / c
            else:
                underlying_move = (c - end_price) / c

            # Option P&L ≈ intrinsic value change / option cost
            if underlying_move > 0:
                option_gain = underlying_move * delta / option_cost_pct
                trade_return = min(option_gain - 1, 3.0)  # cap at 4x
            else:
                trade_return = -1.0  # lose full premium

            # Cap losses at -100% (can't lose more than premium paid)
            trade_return = max(trade_return, -1.0)
            trades.append(trade_return * option_cost_pct)  # in % of portfolio
            i += dte
        else:
            i += 5  # skip ahead looking for signal

    if len(trades) < 3:
        return _empty_backtest()

    trades_arr = np.array(trades)
    win_rate = float(np.mean(trades_arr > 0))
    avg_return = float(np.mean(trades_arr))
    trades_per_year = 252 / dte
    annual_return = (1 + avg_return) ** trades_per_year - 1

    equity = np.cumprod(1 + trades_arr)
    running_max = np.maximum.accumulate(equity)
    drawdown = (equity - running_max) / running_max
    max_drawdown = float(abs(drawdown.min()))

    std = float(np.std(trades_arr))
    sharpe = (avg_return * trades_per_year) / (std * math.sqrt(trades_per_year)) if std > 0 else 0.0

    return {
        "win_rate": round(win_rate * 100, 1),
        "annual_return": round(annual_return * 100, 1),
        "max_drawdown": round(max_drawdown * 100, 1),
        "num_trades": len(trades),
        "sharpe_ratio": round(sharpe, 2),
    }


# ─── 验证逻辑 ─────────────────────────────────────────────────────────────────

def validate_strategy(strategy: dict, backtest_result: dict, min_annual_return: float) -> tuple[bool, str]:
    """
    验证策略是否通过标准

    返回 (passed: bool, reason: str)
    """
    if backtest_result.get("error"):
        return False, f"回测数据不足：{backtest_result.get('error', '未知错误')}"

    annual_return = backtest_result.get("annual_return", 0)
    max_drawdown = backtest_result.get("max_drawdown", 100)
    num_trades = backtest_result.get("num_trades", 0)
    win_rate = backtest_result.get("win_rate", 0)

    if num_trades < 5:
        return False, f"交易次数不足（仅 {num_trades} 笔，需要至少5笔）"

    if annual_return < min_annual_return:
        return False, f"年化收益 {annual_return:.1f}% 低于目标 {min_annual_return:.0f}%"

    if max_drawdown > 40:
        return False, f"最大回撤 {max_drawdown:.1f}% 超过40%阈值"

    if win_rate < 40:
        # For options strategies, lower win rate is OK if return/risk is good
        if strategy.get("instrument") in ("call", "put") and annual_return > min_annual_return * 1.5:
            pass  # allow low win rate for high-return option strategies
        else:
            return False, f"胜率 {win_rate:.1f}% 低于40%最低要求"

    reasons = []
    reasons.append(f"年化收益 {annual_return:.1f}% ≥ 目标 {min_annual_return:.0f}%")
    reasons.append(f"最大回撤 {max_drawdown:.1f}% < 40%")
    reasons.append(f"共 {num_trades} 笔交易，数据充分")
    reasons.append(f"胜率 {win_rate:.1f}%")

    return True, "；".join(reasons)


# ─── 主入口 ──────────────────────────────────────────────────────────────────

async def search_strategies_for_requirements(
    instrument: str = "any",
    direction: str = "any",
    min_annual_return: float = 0.20,
    risk_level: str = "any",
    extra_notes: str = "",
) -> list[dict]:
    """
    根据用户需求搜索并验证策略。

    Step 1: 尝试使用 AI 合成知识库查找策略
    Step 2: 若 AI 不可用，回退到策略库过滤
    Step 3: 对候选策略进行简单回测
    Step 4: 返回通过验证的策略列表
    """
    from strategy_library import filter_library, STRATEGY_LIBRARY
    import json

    candidates = []
    source_badge = "策略库匹配"

    # Step 1: Try AI-powered search
    provider, _ = _get_ai_key_and_provider()
    if provider:
        ai_candidates = await _ai_search_strategies(
            instrument=instrument,
            direction=direction,
            min_annual_return=min_annual_return,
            risk_level=risk_level,
            extra_notes=extra_notes,
        )
        if ai_candidates:
            candidates = ai_candidates
            source_badge = "AI 发现"

    # Step 2: Fallback to library filter
    if not candidates:
        lib_instrument = None if instrument == "any" else instrument
        lib_direction = None if direction == "any" else direction
        lib_risk = None if risk_level == "any" else risk_level
        lib_min_return = int(min_annual_return * 100) if min_annual_return else None

        candidates = filter_library(
            instrument=lib_instrument,
            direction=lib_direction,
            risk_level=lib_risk,
            min_return=lib_min_return,
        )
        source_badge = "策略库匹配"

    # Step 3: Backtest & validate each candidate
    results = []
    for strategy in candidates[:8]:  # Limit to 8 candidates to avoid slow response
        bt = backtest_strategy(strategy, symbol="SPY", years=2)
        passed, reason = validate_strategy(strategy, bt, min_annual_return * 100)
        results.append({
            **strategy,
            "backtest": bt,
            "passed": passed,
            "validation_reason": reason,
            "source_badge": source_badge,
        })

    # Sort: passed first, then by annual_return desc
    results.sort(key=lambda x: (not x["passed"], -x["backtest"].get("annual_return", 0)))
    return results


async def _ai_search_strategies(
    instrument: str,
    direction: str,
    min_annual_return: float,
    risk_level: str,
    extra_notes: str,
) -> list[dict]:
    """
    使用 AI 生成策略建议并解析为标准格式。
    返回策略字典列表，若失败则返回空列表。
    """
    import json

    instrument_cn = {
        "sell_put": "卖 Put", "covered_call": "Covered Call",
        "call": "买 Call", "put": "买 Put", "stock": "正股", "any": "任意工具"
    }.get(instrument, instrument)

    direction_cn = {
        "bullish": "看涨", "bearish": "看跌", "neutral": "中性", "any": "任意方向"
    }.get(direction, direction)

    risk_cn = {
        "low": "低风险", "medium": "中等风险", "high": "高风险", "any": "任意风险"
    }.get(risk_level, risk_level)

    prompt = f"""你是一名量化交易策略专家。请根据以下需求推荐3-5个经过验证的真实交易策略：

用户需求：
- 交易工具：{instrument_cn}
- 市场方向：{direction_cn}
- 年化收益目标：{min_annual_return*100:.0f}%+
- 风险偏好：{risk_cn}
- 补充说明：{extra_notes or "无"}

请以 JSON 数组格式输出，每个策略包含以下字段（全部必填）：
[
  {{
    "id": "unique_slug",
    "name": "策略名称（中文）",
    "description": "2-3句话描述入场/出场/条件",
    "source": "数据来源/参考文献",
    "instrument": "stock/call/put/sell_put/covered_call",
    "direction": "bullish/bearish/neutral",
    "style": "income/growth/hedge/momentum/mean_reversion",
    "risk_level": "low/medium/high",
    "annual_return_range": [最低预期%, 最高预期%],
    "win_rate_pct": 胜率整数,
    "params": {{}},
    "tags": ["标签1", "标签2"],
    "why_it_works": "1-2句解释策略有效性的原理",
    "best_market": "最适合的市场条件",
    "worst_market": "最糟糕的市场条件"
  }}
]

只输出 JSON，不要其他文字。使用真实、有据可查的策略数据。"""

    response = _call_ai(prompt, max_tokens=2000)
    if not response:
        return []

    try:
        # Extract JSON from response
        text = response.strip()
        # Find JSON array
        start = text.find("[")
        end = text.rfind("]") + 1
        if start == -1 or end == 0:
            return []
        json_str = text[start:end]
        strategies = json.loads(json_str)

        # Validate and normalize each strategy
        normalized = []
        for s in strategies:
            if not isinstance(s, dict):
                continue
            # Ensure required fields exist
            if not all(k in s for k in ["id", "name", "instrument", "direction"]):
                continue
            # Set defaults for missing fields
            s.setdefault("params", {})
            s.setdefault("tags", [])
            s.setdefault("style", "income")
            s.setdefault("risk_level", "medium")
            s.setdefault("annual_return_range", [15, 30])
            s.setdefault("win_rate_pct", 60)
            s.setdefault("why_it_works", "")
            s.setdefault("best_market", "")
            s.setdefault("worst_market", "")
            s.setdefault("description", "")
            s.setdefault("source", "AI 研究")
            normalized.append(s)

        return normalized
    except (json.JSONDecodeError, ValueError) as e:
        logger.warning(f"Failed to parse AI strategy response: {e}")
        return []
