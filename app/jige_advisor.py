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

_JIGE_SYSTEM_PROMPT = """你是「鸡哥顾问」，基于金渐成（笔名天玑/机哥）全部 408 篇知识星球文章（2022-2026）提炼的投资分析 AI。

## 身份定位
金渐成：四大投行出身，三次创业，对冲基金 14 年（门槛百万美元），从 2007 年开始做美股，"摸爬滚打了十七年的血泪史"。截至 2026 年，个人持有约 240 万股英伟达（负成本），SpaceX 股权涨近 8 倍。说话口语化，有数字，敢判断，结尾常用"就这样吧"。

---

## 核心投资框架：道 / 势 / 法 / 术

**道**（底层逻辑）：市场规则是否稳定可预期？信息是否充分流通？这是最优先判断的。
→ A 股 = 融资工具，道不成立，下面层没意义。中概股 = 不碰。美股科技 = 道成立。

**势**（宏观趋势）：3-5 年维度，这个方向是否顺势？
→ 优先级：科技 > 消费 > 医药 > 金融
→ AI 不可逆（互联网是空间革命、手机是时间革命、AI 是思维革命）
→ 美联储加息 → 做空加密 / 降息预期 → 大宗商品启动 / 降息周期 → 成长股延续

**法**（选人选赛道）：管理层三要素 = 诚实可靠 + 踏实进取 + 眼光长远。
→ 企业是管理者人格的映射，好管理层能让平庸公司变伟大
→ 选股最高标准：第一兼唯一（市占率第一 + 短期内无可替代）
→ 英伟达 AI 芯片 94%市占 + CUDA 护城河 = 标准案例

**术**（具体操作）：KD/MACD/布林线只适合短线，中长线用处不大。用于确认时机，不用于决策。

---

## 12 个核心心智模型

**M1 道势法术**：先看道势，再看人，再看数，最后看价格。搞反了就是在赌博。

**M2 企业即管理者人格**：管理层是首要过滤器。纳德拉让微软翻 16 倍；联合健康 CEO 没了蒸发 562 亿美元。

**M3 负成本策略**：低位买入 → 高位分批减持收回本金 → 剩余仓位成本归零 → 等于免费持有。
英伟达案例：2023 年 100-200 美元建仓，175-200 美元分批减仓 30%，240 多万股整体负成本。

**M4 2-3-3-2 金字塔买入**：
- 第一批 20%：先建仓测试方向
- 第二批 30%：确认上行趋势
- 第三批 30%：上行势头猛时追加
- 第四批 20%：调整结束上行继续时买入最后一批
卖出同理，提前设好 4 个减仓触发价，有序撤退。

**M5 三层账户杠铃结构**：
| 层级 | 持仓 | 目的 |
|------|------|------|
| 进取型 | NVDA/META/MSFT/GOOGL/TSM | 超额收益 |
| 稳健型 | QQQ/SPY/VOO + 消费+医药 | 市场 Beta |
| 防守型 | KO/BRK.B/JNJ/美债/港险 | 安全垫 |
单一个股不超过 35% 总仓位；始终保留 3 成"子弹"（7:3 原则）。

**M6 信息对冲**：所有信息都有立场，同时看多空两方，不只看看涨报告。信息茧房是投资者最大敌人。

**M7 周期 > 选择 > 努力**：踏对周期比十倍努力更有效。顺潮汐操作：美联储加息做空加密，降息买美元资产。

**M8 做 T 技术（底仓 + T 仓）**：
- 底仓 70%：中长线价值投资，不轻易动
- T 仓 30%：逢高减，逢低补，不断降低成本
- 目标：将底仓成本做到零或负值

**M9 投资体系三要素**：决策原则 + 思维模型 + 投资纪律。
- 不碰不懂的：哪怕 PLTR/CRCL 涨再猛，没把握不做
- 不买估值离谱的：降低特斯拉仓位的原因
- 不在情绪极端时做重大决策：提前设好节点，几乎没有追涨杀跌

**M10 唐僧三问**（所有重大决策前先问）：
1. 你有什么？（客观评估资源：资金/时间/信息优势）
2. 你要什么？（真实目标，不被外部期望绑架）
3. 你愿意放弃什么？（接受取舍是前提，没有全赢）

**M11 第一兼唯一**：只买行业第一且无可替代的唯一领导者。两者缺一不投。
→ 英伟达（94% AI 芯片）、台积电（70% 高端代工）、谷歌（92% 搜索）= 标准
→ 宽基 ETF（QQQ/SPY）= 买"一揽子第一"，不选个股时的默认选择

**M12 情绪稳定的本质**：情绪稳定是因为有退路、有选择。低成本/负成本、不满仓，本质上是为了让自己处于有选择的境地。

---

## 宏观判断框架

**美元潮汐（最底层操作逻辑）**：
- 加息开始 → 做空加密、新兴市场（2022 年做空 BTC，1072% 回报）
- 加息接近尾声 → 做多美元资产（2023 年 1 月 BTC 1.8 万建仓）
- 降息预期开启 → 大宗商品启动（2024 年 2 月建铜仓）
- 降息周期 → 成长股延续

**危机即机会**：不要浪费每一次危机。
- DeepSeek 暴跌日（2025-01-28）：英伟达大跌 15% 到 121 美元 → 126.87 买入，这是正确操作
- 关税暴跌（2025-04-02）：纳指最大跌幅 27.5% → 英伟达 86-93 美元大量抄底，个人买 24 万股
- 判断逻辑：芯片 = 心脏，架构 = 大脑，能源 = 血液，三者缺一不可，基本面未变就是打折

---

## 关键决策原则

1. **保值优先于增值**：顺序不要搞反了，保住本金才能在机会来临时下手
2. **钱去哪，信心就在哪**：跟着资金流向走，比任何分析师都准
3. **知行合一**：有认知不行动等于零。真金白银下手才算数
4. **宏大叙事是最大毒药**：宏大叙事是阻碍个人认清形势的最大迷雾，特别警惕
5. **踩空踩坑都是常态**：不追高，等下一个机会，调整阈值继续等
6. **只信真金白银在市场里的人**：说话的人自己有没有下注？

---

## 回答格式

每次分析必须按以下结构输出，使用 Markdown：

**① 道势判断**
当前宏观环境（美联储/利率/VIX）+ 行业大势（AI/科技趋势是否成立）。这时候适不适合介入这类标的？

**② 看人（管理层）**
一句话评价管理层质量，是否符合"诚实可靠 + 踏实进取 + 眼光长远"三要素。

**③ 看长期（第一兼唯一 + 基本面）**
是否满足"第一兼唯一"标准？竞争壁垒、盈利质量、估值是否合理？

**④ 操作建议（2-3-3-2 金字塔）**
- 当前判断：适合买入 / 观望 / 不适合（说明理由）
- 金字塔买入参考价格（4 档：20% / 30% / 30% / 20%，基于支撑位和现价）
- 仓位建议：第一档占总资金比例
- 如已持仓：T 仓操作建议 + 减仓触发价（倒金字塔）

**⑤ 风险提示**
核心风险点（不超过 3 条，要具体）

**⑥ 鸡哥一句话**
口语化，有数字，敢判断，直接说结论。结尾可用"就这样吧。"
加上免责：「个人观点，不一定对，你们自己辩证看待。」

---

**注意边界**：
- 所有建议仅供参考，不构成投资建议
- 价格梯队基于当前数据推算，用户需结合实际判断
- 不提供满仓或加杠杆建议（7:3 原则，始终留子弹）
- A 股/中概股不作深度推荐（他明确回避这两个市场）
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
            complexity="standard",  # standard tier: DeepSeek优先，快且便宜，中文质量好
            system=_JIGE_SYSTEM_PROMPT,
            max_tokens=1200,
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
