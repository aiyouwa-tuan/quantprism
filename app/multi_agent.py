"""
Goal-Driven Trading OS — Multi-Agent Analysis System
4 parallel analysts → Bull/Bear debate → Research Manager verdict → Risk review

Step latency budget:
  Step 1: Memory retrieval (BM25, <100ms)
  Step 2: 4 analysts in parallel (~3-5s)
  Step 3: Bull vs Bear debate (~6s sequential)
  Step 4: Research Manager verdict (~3s)
  Step 5: Risk review (3 debaters, ~9-12s, separate flow at trade time)
"""
import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Analyst prompts
# ---------------------------------------------------------------------------

def _fundamental_analyst_prompt(symbol: str, fundamentals: dict, similar_memories: list) -> str:
    memory_context = _format_memories(similar_memories)
    pe = fundamentals.get("pe_ratio", "N/A")
    eps = fundamentals.get("eps", "N/A")
    mkt_cap = _fmt_large(fundamentals.get("market_cap"))
    analyst_rating = fundamentals.get("analyst_rating", "N/A")
    target = fundamentals.get("analyst_target", "N/A")
    earnings_date = fundamentals.get("earnings_date", "N/A")
    revenue = _fmt_large(fundamentals.get("revenue"))
    roe = fundamentals.get("return_on_equity")
    roe_str = f"{roe*100:.1f}%" if roe else "N/A"
    margins = fundamentals.get("profit_margins")
    margins_str = f"{margins*100:.1f}%" if margins else "N/A"

    return f"""你是一位基本面分析师，专注于评估公司财务健康状况。

标的: {symbol}
市值: {mkt_cap} | PE: {pe} | EPS: {eps}
营收: {revenue} | ROE: {roe_str} | 利润率: {margins_str}
分析师评级: {analyst_rating} | 目标价: ${target}
下次财报日: {earnings_date}

{memory_context}

请从基本面角度分析 {symbol}，给出：
1. 估值是否合理？（PE/EPS vs 行业均值）
2. 盈利质量和成长性
3. 关键财务风险
4. 基本面评分（0-10）和一句话结论

用中文回答，控制在200字以内。"""


def _technical_analyst_prompt(symbol: str, diagnosis: dict, similar_memories: list) -> str:
    memory_context = _format_memories(similar_memories)
    return f"""你是一位技术分析师，专注于价格走势和技术指标。

标的: {symbol}
当前价: ${diagnosis.get('current_price', 0):.2f}
趋势: {diagnosis.get('trend', 'unknown')} | RSI: {diagnosis.get('rsi', 0):.0f}
SMA20: ${diagnosis.get('sma_20', 0):.2f} | SMA50: ${diagnosis.get('sma_50', 0):.2f} | SMA200: ${diagnosis.get('sma_200', 0):.2f}
布林带位置: {diagnosis.get('bb_position', 'unknown')} | ATR(14): ${diagnosis.get('atr_14', 0):.2f}
支撑位: ${diagnosis.get('support_level', 0):.2f} | 安全边际: {diagnosis.get('safety_margin', 0)*100:.1f}%
IV Rank: {diagnosis.get('iv_rank', 0):.0f}

{memory_context}

请从技术面角度分析 {symbol}，给出：
1. 当前价格结构和趋势强度
2. 关键支撑/阻力位
3. RSI/布林带信号解读
4. 技术面评分（0-10）和一句话结论

用中文回答，控制在200字以内。"""


def _news_analyst_prompt(symbol: str, news: list, similar_memories: list) -> str:
    memory_context = _format_memories(similar_memories)
    news_text = "\n".join([
        f"- [{art.get('source', '')}] {art.get('title', '')} ({art.get('published', '')[:10]})"
        for art in news[:5]
    ]) if news else "暂无最新新闻"

    return f"""你是一位新闻分析师，专注于识别影响股价的事件驱动因素。

标的: {symbol}
最新新闻:
{news_text}

{memory_context}

请从新闻事件角度分析 {symbol}，给出：
1. 近期重要事件概述
2. 对股价的短期影响（利好/利空/中性）
3. 需要关注的催化剂
4. 新闻面评分（0-10）和一句话结论

用中文回答，控制在200字以内。"""


def _sentiment_analyst_prompt(symbol: str, diagnosis: dict, news: list) -> str:
    # Simple sentiment proxy: RSI + news count + iv_rank
    rsi = diagnosis.get("rsi", 50)
    iv_rank = diagnosis.get("iv_rank", 50)
    news_count = len(news)

    return f"""你是一位市场情绪分析师，专注于评估市场参与者的情绪和行为。

标的: {symbol}
RSI(14): {rsi:.0f} | IV Rank: {iv_rank:.0f}
过去7天新闻数量: {news_count}
当前趋势: {diagnosis.get('trend', 'unknown')}
BB位置: {diagnosis.get('bb_position', 'unknown')}

请从市场情绪角度分析 {symbol}，给出：
1. 当前市场情绪（贪婪/恐慌/中性）
2. 期权市场隐含的情绪信号（基于IV Rank）
3. 散户 vs 机构行为判断
4. 情绪面评分（0-10）和一句话结论

用中文回答，控制在150字以内。"""


def _bull_prompt(symbol: str, analyses: dict) -> str:
    return f"""你是多头辩手，必须为看涨 {symbol} 辩护。

四位分析师的观点摘要:
基本面: {analyses.get('fundamental', '无数据')[:200]}
技术面: {analyses.get('technical', '无数据')[:200]}
新闻面: {analyses.get('news', '无数据')[:200]}
情绪面: {analyses.get('sentiment', '无数据')[:150]}

请给出最有力的3个做多理由，以及应对空头质疑的论据。
格式：直接给出论点，不要复述问题。控制在250字以内。"""


def _bear_prompt(symbol: str, analyses: dict, bull_argument: str) -> str:
    return f"""你是空头辩手，必须反驳多头论点并给出做空/观望理由。

多头论点:
{bull_argument[:400]}

请给出最有力的3个做空/观望理由，直接反驳多头的核心论点。
格式：直接给出反驳，不要复述多头论点。控制在250字以内。"""


def _verdict_prompt(symbol: str, analyses: dict, bull_argument: str, bear_argument: str,
                    diagnosis: dict) -> str:
    return f"""你是研究总监，需要综合多空辩论给出最终投资裁决。

标的: {symbol} | 当前价: ${diagnosis.get('current_price', 0):.2f}
支撑位: ${diagnosis.get('support_level', 0):.2f} | 综合评分: {diagnosis.get('score', 0)}/100

多头论点摘要:
{bull_argument[:300]}

空头论点摘要:
{bear_argument[:300]}

请给出：
1. 最终立场（强烈看多/看多/中性/看空/强烈看空）
2. 建议操作（买正股/买Call/Sell Put/Covered Call/观望）
3. 如果做Sell Put: 建议行权价区间和到期日
4. 核心风险提示（1条最重要的）
5. 一句话总结

用中文，简洁直接，控制在200字以内。"""


# ---------------------------------------------------------------------------
# Risk review prompts
# ---------------------------------------------------------------------------

def _aggressive_risk_prompt(symbol: str, signal: dict, diagnosis: dict) -> str:
    return f"""你是激进型风险评估员，倾向于接受更高风险换取更高收益。

信号: {symbol} | 方向: {signal.get('direction', 'N/A')} | 价格: ${signal.get('price', 0):.2f}
支撑位: ${diagnosis.get('support_level', 0):.2f} | 安全边际: {diagnosis.get('safety_margin', 0)*100:.1f}%
IV Rank: {diagnosis.get('iv_rank', 0):.0f} | RSI: {diagnosis.get('rsi', 0):.0f}

从激进视角评估此交易，给出：
1. 为什么风险可接受（不超过3条理由）
2. 建议的最大仓位（占总资金%）
3. 止损设置建议

控制在150字以内。"""


def _neutral_risk_prompt(symbol: str, signal: dict, diagnosis: dict) -> str:
    return f"""你是中性型风险评估员，追求风险收益平衡。

信号: {symbol} | 方向: {signal.get('direction', 'N/A')} | 价格: ${signal.get('price', 0):.2f}
支撑位: ${diagnosis.get('support_level', 0):.2f} | 安全边际: {diagnosis.get('safety_margin', 0)*100:.1f}%
IV Rank: {diagnosis.get('iv_rank', 0):.0f} | RSI: {diagnosis.get('rsi', 0):.0f}

从中性视角评估此交易，给出：
1. 主要风险与机会的平衡分析
2. 建议的标准仓位（占总资金%）
3. 风险管理措施

控制在150字以内。"""


def _conservative_risk_prompt(symbol: str, signal: dict, diagnosis: dict) -> str:
    return f"""你是保守型风险评估员，以资本保护为首要原则。

信号: {symbol} | 方向: {signal.get('direction', 'N/A')} | 价格: ${signal.get('price', 0):.2f}
支撑位: ${diagnosis.get('support_level', 0):.2f} | 安全边际: {diagnosis.get('safety_margin', 0)*100:.1f}%
IV Rank: {diagnosis.get('iv_rank', 0):.0f} | RSI: {diagnosis.get('rsi', 0):.0f}

从保守视角评估此交易，给出：
1. 为什么应该谨慎或等待（不超过3条理由）
2. 最小化风险的建议仓位（占总资金%）
3. 需要满足什么条件才值得进场

控制在150字以内。"""


def _risk_verdict_prompt(symbol: str, aggressive: str, neutral: str, conservative: str,
                         signal: dict) -> str:
    return f"""你是首席风险官，需要综合三位风险评估员的意见给出最终风险裁决。

标的: {symbol}
激进型评估: {aggressive[:200]}
中性型评估: {neutral[:200]}
保守型评估: {conservative[:200]}

请给出：
1. 风险裁决（高风险/中等风险/低风险）
2. 建议仓位（具体%，如 "建议总资金的 3-5%"）
3. 必须设置的止损位
4. 最多1条最关键的风险警告

用中文，简洁直接，控制在150字以内。"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _format_memories(memories: list) -> str:
    if not memories:
        return ""
    lines = ["**历史相似案例参考:**"]
    for m in memories[:3]:
        lines.append(f"- {m.get('date', '')} {m.get('symbol', '')}: {m.get('scenario', '')[:80]} | 结果: {m.get('outcome', 'N/A')} | 教训: {m.get('lesson', '')[:60]}")
    return "\n".join(lines) + "\n"


def _fmt_large(value) -> str:
    if value is None:
        return "N/A"
    try:
        v = float(value)
        if v >= 1e12:
            return f"${v/1e12:.1f}T"
        elif v >= 1e9:
            return f"${v/1e9:.1f}B"
        elif v >= 1e6:
            return f"${v/1e6:.1f}M"
        return f"${v:,.0f}"
    except Exception:
        return "N/A"


# ---------------------------------------------------------------------------
# Main multi-agent analysis
# ---------------------------------------------------------------------------

def run_analysis(symbol: str, diagnosis: dict, fundamentals: dict = None,
                 news: list = None, similar_memories: list = None) -> dict:
    """
    Run 4 parallel analysts + bull/bear debate + verdict.

    Args:
        symbol: Stock symbol
        diagnosis: StockDiagnosis as dict (from diagnose_stock)
        fundamentals: From fetch_fundamentals()
        news: From fetch_news()
        similar_memories: From retrieve_similar() BM25 results

    Returns:
        dict with keys: analysts, bull, bear, verdict, error (if any)
    """
    from ai_analysis import call_ai

    fundamentals = fundamentals or {}
    news = news or []
    similar_memories = similar_memories or []

    # Step 1: Build prompts
    prompts = {
        "fundamental": (_fundamental_analyst_prompt(symbol, fundamentals, similar_memories), "standard"),
        "technical": (_technical_analyst_prompt(symbol, diagnosis, similar_memories), "standard"),
        "news": (_news_analyst_prompt(symbol, news, similar_memories), "cheap"),
        "sentiment": (_sentiment_analyst_prompt(symbol, diagnosis, news), "cheap"),
    }

    # Step 2: Run 4 analysts in parallel
    analysts = {}
    analyst_errors = {}

    def _run_analyst(name: str, prompt: str, complexity: str) -> tuple:
        try:
            result = call_ai(prompt, complexity=complexity, max_tokens=600)
            return name, result, None
        except Exception as e:
            logger.warning(f"Analyst {name} failed: {e}")
            return name, None, str(e)

    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = {
            executor.submit(_run_analyst, name, prompt, complexity): name
            for name, (prompt, complexity) in prompts.items()
        }
        for future in as_completed(futures):
            name, result, error = future.result()
            if result:
                analysts[name] = result
            else:
                analysts[name] = f"[分析失败: {error}]"
                analyst_errors[name] = error

    # Step 3: Bull/Bear debate (sequential)
    bull_argument = ""
    bear_argument = ""
    try:
        bull_argument = call_ai(_bull_prompt(symbol, analysts), complexity="strong", max_tokens=600)
    except Exception as e:
        bull_argument = f"[多头辩论失败: {e}]"
        logger.warning(f"Bull debate failed: {e}")

    try:
        bear_argument = call_ai(_bear_prompt(symbol, analysts, bull_argument), complexity="strong", max_tokens=600)
    except Exception as e:
        bear_argument = f"[空头辩论失败: {e}]"
        logger.warning(f"Bear debate failed: {e}")

    # Step 4: Research Manager verdict
    verdict = ""
    try:
        verdict = call_ai(
            _verdict_prompt(symbol, analysts, bull_argument, bear_argument, diagnosis),
            complexity="strong",
            max_tokens=600,
        )
    except Exception as e:
        verdict = f"[裁决生成失败: {e}]"
        logger.warning(f"Verdict failed: {e}")

    return {
        "symbol": symbol,
        "analysts": analysts,
        "bull": bull_argument,
        "bear": bear_argument,
        "verdict": verdict,
        "timestamp": datetime.now().isoformat(),
        "errors": analyst_errors if analyst_errors else None,
    }


# ---------------------------------------------------------------------------
# Risk review (separate flow, triggered at trade confirmation)
# ---------------------------------------------------------------------------

def run_risk_review(symbol: str, signal: dict, diagnosis: dict) -> dict:
    """
    3-way risk debate: aggressive vs neutral vs conservative, then verdict.

    Args:
        symbol: Stock symbol
        signal: Trade signal dict {direction, price, strike, expiry, ...}
        diagnosis: StockDiagnosis as dict

    Returns:
        dict with keys: aggressive, neutral, conservative, verdict
    """
    from ai_analysis import call_ai

    # 3 debaters in parallel
    def _call(prompt: str) -> str:
        try:
            return call_ai(prompt, complexity="strong", max_tokens=400)
        except Exception as e:
            return f"[评估失败: {e}]"

    with ThreadPoolExecutor(max_workers=3) as executor:
        f_agg = executor.submit(_call, _aggressive_risk_prompt(symbol, signal, diagnosis))
        f_neu = executor.submit(_call, _neutral_risk_prompt(symbol, signal, diagnosis))
        f_con = executor.submit(_call, _conservative_risk_prompt(symbol, signal, diagnosis))

    aggressive = f_agg.result()
    neutral = f_neu.result()
    conservative = f_con.result()

    # Risk verdict
    try:
        verdict = call_ai(
            _risk_verdict_prompt(symbol, aggressive, neutral, conservative, signal),
            complexity="strong",
            max_tokens=400,
        )
    except Exception as e:
        verdict = f"[风险裁决失败: {e}]"

    return {
        "symbol": symbol,
        "aggressive": aggressive,
        "neutral": neutral,
        "conservative": conservative,
        "verdict": verdict,
        "timestamp": datetime.now().isoformat(),
    }
