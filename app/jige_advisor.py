"""
鸡哥顾问 — 金渐成投资原则 AI 分析
用户输入股票代码，自动拉取实时数据，以金渐成风格给出买卖建议。
"""
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 金渐成核心原则 System Prompt
# ---------------------------------------------------------------------------

_JIGE_SYSTEM_PROMPT = """你是「鸡哥顾问」，一个严格遵循金渐成投资体系的 AI 顾问。

## 金渐成核心投资原则

### 七大哲学
- P1 在有鱼的地方钓鱼：只投美股优质资产，远离垃圾股和概念股
- P2 先防守后进攻：任何时候先确保不被淘汰出局，再谈怎么赢
- P3 永不满仓：常规仓位上限 75%，始终保留 ≥25% 现金
- P4 耐心等时间：中长线持仓为主，短线技术指标是"术"，看大势和看人是"道"
- P5 危机是礼物：熊市/急跌是打折买优质资产的机会，区分"基本面变化"vs"短期扰动"
- P6 学思路不抄作业：看别人的逻辑和思路，不盲目照搬买卖节点
- P7 超额收益时更要加强防守：赚钱时把利润部分转入防守型配置

### 选股三维度
- D1 看大势：站在 AI/云计算等时代趋势正确一边；关注美联储利率、通胀趋势
- D2 看人（管理层）：诚实可靠、踏实进取、眼光长远；好管理层能让平庸公司变伟大
- D3 看长期：商业模式、竞争壁垒、基本面质量；只买看得懂的公司

### 账户分层
- 进取型：科技龙头（NVDA/MSFT/GOOGL/AMZN/TSM 等），目标超额收益
- 稳健型：蓝筹+成长混合
- 防守型（≥40% 总资产）：高股息（KO/MO/JNJ/PG/BRK）+ 红利 ETF（SCHD/XLP）

### 买入：金字塔加仓
- 提前设定 3-5 个买入价格梯队，触发则执行不追高
- 第一笔最大，后续递减；越跌越买，控制总投入
- 危机识别：基本面未变 → 加仓机会；基本面已变 → 观望/减仓

### 卖出：倒金字塔减仓
- 提前设定 3-5 个减仓价格梯队
- 小量开始逐步锁定利润，目标"做零成本"（卖回本金）
- 市场情绪狂热时减仓，不贪心等最高点

### 风险控制
- 常规仓位 ≤75%，极端抄底最多动用现金储备的 50%
- 零杠杆：绝不融资，不借钱投资
- 攻守再平衡：进取型收益 +30% 以上时，套现部分利润转入防守型

## 你的回答格式

每次分析必须按以下结构输出，使用 Markdown：

**① 大势判断**
当前宏观环境和市场趋势，这时候适不适合介入这类标的？

**② 看人（管理层）**
一句话评价公司管理层质量，影响长期价值的关键点。

**③ 看长期（基本面 + 商业模式）**
公司竞争壁垒、盈利质量、估值是否合理？

**④ 操作建议**
根据金字塔原则，给出具体的：
- 当前是否适合买入？（是/观望/不适合，说明理由）
- 金字塔买入参考价格梯队（3 档，基于支撑位和现价）
- 仓位建议（第一档占总资金的 X%）
- 如已持仓，倒金字塔减仓参考价格

**⑤ 风险提示**
核心风险点（不超过 3 条）

**⑥ 鸡哥一句话**
金渐成风格的总结，直接、有力、有态度。

---
注意：
- 你是投资顾问，不是交易执行系统，所有建议仅供参考
- 价格梯队基于当前数据推算，用户需结合实际判断
- 严格遵循零杠杆、永不满仓原则，不给出全仓或加杠杆建议
"""


def _fmt_large(v) -> str:
    if v is None:
        return "N/A"
    try:
        v = float(v)
        if v >= 1e12:
            return f"${v/1e12:.2f}T"
        if v >= 1e9:
            return f"${v/1e9:.2f}B"
        if v >= 1e6:
            return f"${v/1e6:.2f}M"
        return f"${v:,.0f}"
    except Exception:
        return str(v)


def gather_stock_context(symbol: str) -> dict:
    """拉取股票的实时数据：价格、技术指标、基本面、新闻、市场状态"""
    import dataclasses
    from stock_screener import diagnose_stock
    from data_providers import fetch_fundamentals, fetch_news
    from market_data import detect_market_regime, fetch_current_price

    symbol = symbol.upper()
    ctx = {"symbol": symbol, "error": None}

    # 价格 + 技术诊断
    try:
        price_data = fetch_current_price(symbol)
        ctx["price"] = price_data.get("price")
        ctx["change_pct"] = price_data.get("change_pct")
    except Exception as e:
        logger.warning(f"fetch_current_price({symbol}) failed: {e}")
        ctx["price"] = None
        ctx["change_pct"] = None

    try:
        diag = diagnose_stock(symbol)
        ctx["diag"] = dataclasses.asdict(diag)
    except Exception as e:
        logger.warning(f"diagnose_stock({symbol}) failed: {e}")
        ctx["diag"] = {}

    # 基本面
    try:
        ctx["fundamentals"] = fetch_fundamentals(symbol)
    except Exception as e:
        logger.warning(f"fetch_fundamentals({symbol}) failed: {e}")
        ctx["fundamentals"] = {}

    # 新闻（最新 5 条）
    try:
        news = fetch_news(symbol, limit=5)
        ctx["news"] = [n.get("headline", "") for n in news if n.get("headline")][:5]
    except Exception as e:
        logger.warning(f"fetch_news({symbol}) failed: {e}")
        ctx["news"] = []

    # 市场状态
    try:
        ctx["regime"] = detect_market_regime()
    except Exception as e:
        logger.warning(f"detect_market_regime failed: {e}")
        ctx["regime"] = {}

    return ctx


def build_user_message(symbol: str, ctx: dict, user_question: str = "") -> str:
    """将股票数据整合为用户消息"""
    diag = ctx.get("diag", {})
    fund = ctx.get("fundamentals", {})
    regime = ctx.get("regime", {})
    news = ctx.get("news", [])

    price = ctx.get("price")
    change_pct = ctx.get("change_pct")
    price_str = f"${price:.2f}" if price else "N/A"
    change_str = f"({change_pct:+.2f}%)" if change_pct is not None else ""

    trend = diag.get("trend", "N/A")
    rsi = diag.get("rsi", "N/A")
    support = diag.get("support_level")
    support_str = f"${support:.2f}" if support else "N/A"
    score = diag.get("score", "N/A")

    sma_20 = diag.get("sma_20")
    sma_50 = diag.get("sma_50")
    sma_200 = diag.get("sma_200")

    pe = fund.get("pe_ratio")
    eps = fund.get("eps")
    mkt_cap = _fmt_large(fund.get("market_cap"))
    sector = fund.get("sector", "N/A")
    analyst_rating = fund.get("analyst_rating", "N/A")
    analyst_target = fund.get("analyst_target")
    target_str = f"${analyst_target:.2f}" if analyst_target else "N/A"
    week_52_high = fund.get("week_52_high")
    week_52_low = fund.get("week_52_low")
    roe = fund.get("return_on_equity")
    margins = fund.get("profit_margins")
    beta = fund.get("beta")

    regime_label = regime.get("label", "N/A")
    vix = regime.get("vix")
    vix_str = f"{vix:.1f}" if vix else "N/A"

    news_block = ""
    if news:
        news_block = "\n**近期新闻（最新 5 条）：**\n" + "\n".join(f"- {h}" for h in news)

    question_block = f"\n\n**用户问题：** {user_question}" if user_question else ""

    lines = [
        f"请分析 **{symbol}**",
        "",
        f"**当前价格：** {price_str} {change_str}",
        f"**市场状态：** {regime_label}，VIX={vix_str}",
        "",
        "**技术指标：**",
        f"- 趋势：{trend}",
        f"- RSI(14)：{rsi:.1f}" if isinstance(rsi, float) else f"- RSI(14)：{rsi}",
        f"- 技术评分：{score}/100" if isinstance(score, (int, float)) else f"- 技术评分：{score}",
        f"- 关键支撑位：{support_str}",
        f"- SMA20/50/200：${sma_20:.2f} / ${sma_50:.2f} / ${sma_200:.2f}" if all(x is not None for x in [sma_20, sma_50, sma_200]) else "",
        f"- 52周区间：${week_52_low:.2f} ~ ${week_52_high:.2f}" if week_52_low and week_52_high else "",
        "",
        "**基本面：**",
        f"- 市值：{mkt_cap}  |  行业：{sector}",
        f"- PE：{pe:.1f}" if isinstance(pe, float) else f"- PE：{pe}",
        f"- EPS：{eps:.2f}" if isinstance(eps, float) else f"- EPS：{eps}",
        f"- ROE：{roe*100:.1f}%" if roe else "",
        f"- 净利润率：{margins*100:.1f}%" if margins else "",
        f"- Beta：{beta:.2f}" if isinstance(beta, float) else "",
        f"- 分析师评级：{analyst_rating}  |  目标价：{target_str}",
    ]

    # 过滤空行（保留段落分隔空行）
    filtered = []
    for l in lines:
        filtered.append(l)

    message = "\n".join(filtered)
    message += news_block
    message += question_block

    return message


def run_jige_analysis(symbol: str, user_question: str = "") -> dict:
    """
    主入口：拉取数据 → 构建 prompt → 调用 AI → 返回结果
    返回 dict: {symbol, price, change_pct, analysis, error, timestamp}
    """
    from ai_analysis import call_ai

    symbol = symbol.upper()

    # 1. 拉取数据
    ctx = gather_stock_context(symbol)

    # 2. 构建用户消息
    user_msg = build_user_message(symbol, ctx, user_question)

    # 3. 调用 AI（strong tier）
    try:
        analysis = call_ai(
            prompt=user_msg,
            complexity="strong",
            system=_JIGE_SYSTEM_PROMPT,
            max_tokens=1200,  # 1800→1200：分析够用，响应更快（约 68s 超时）
        )
    except Exception as e:
        logger.error(f"jige AI call failed: {e}")
        return {
            "symbol":     symbol,
            "price":      ctx.get("price"),
            "change_pct": ctx.get("change_pct"),
            "analysis":   None,
            "error":      f"AI 分析失败：{e}",
            "timestamp":  datetime.now().strftime("%Y-%m-%d %H:%M"),
            "rsi":        None,
            "trend":      None,
        }

    diag = ctx.get("diag", {})
    return {
        "symbol":     symbol,
        "price":      ctx.get("price"),
        "change_pct": ctx.get("change_pct"),
        "analysis":   analysis,
        "error":      None,
        "timestamp":  datetime.now().strftime("%Y-%m-%d %H:%M"),
        "rsi":        diag.get("rsi"),
        "trend":      diag.get("trend"),
    }
