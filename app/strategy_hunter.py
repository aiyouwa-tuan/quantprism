"""
Goal-Driven Trading OS — Strategy Hunter
搜索 GitHub 策略仓库 + AI 生成策略 + 匹配评分
"""
import json
import logging
import os
from datetime import datetime, timedelta, timezone

import httpx

logger = logging.getLogger(__name__)


# ─── AI 调用（复用 ai_analysis 的配置）──────────────────────────────────────────

def _call_ai(prompt: str, max_tokens: int = 2000) -> str | None:
    """调用当前可用 AI 返回文本，复用 ai_analysis 的 provider 配置"""
    from ai_analysis import (
        AI_PROVIDERS,
        get_active_provider,
        _call_openai_compatible,
        _call_claude,
        _call_gemini,
    )

    provider = get_active_provider()
    if not provider:
        return None

    cfg = AI_PROVIDERS[provider]
    key = os.getenv(cfg["env_key"])
    try:
        if provider in ("deepseek", "openai"):
            result = _call_openai_compatible(
                cfg["base_url"], key, cfg["model"], prompt, provider
            )
        elif provider == "claude":
            result = _call_claude(key, cfg["model"], prompt)
        elif provider == "gemini":
            result = _call_gemini(key, cfg["model"], prompt)
        else:
            return None
        return result.get("analysis")
    except Exception as e:
        logger.warning("Strategy Hunter AI call failed: %s", e)
        return None


# ─── 1. GitHub 搜索 ─────────────────────────────────────────────────────────────

GITHUB_SEARCH_URL = "https://api.github.com/search/repositories"

# 常用搜索关键词模板
DEFAULT_QUERIES = [
    "quantitative trading strategy",
    "algorithmic trading python",
    "backtest trading strategy",
    "stock trading bot python",
]


def search_github_strategies(
    query: str, min_stars: int = 10
) -> list[dict]:
    """
    用 GitHub Search API 搜索交易策略仓库。

    Args:
        query: 搜索关键词（如 "momentum strategy", "mean reversion"）
        min_stars: 最少星数过滤

    Returns:
        Top 10 仓库列表：name, url, stars, description, last_updated
        若遇到限流则返回空列表 + 日志警告
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=730)  # 2 年内有更新
    params = {
        "q": f"{query} language:python",
        "sort": "stars",
        "order": "desc",
        "per_page": 30,  # 多拉一些以便过滤
    }

    try:
        resp = httpx.get(
            GITHUB_SEARCH_URL,
            params=params,
            headers={"Accept": "application/vnd.github+json"},
            timeout=15,
        )

        # 限流处理
        if resp.status_code == 403:
            remaining = resp.headers.get("X-RateLimit-Remaining", "?")
            logger.warning(
                "GitHub API rate limited (remaining=%s). 返回空列表。", remaining
            )
            return []

        if resp.status_code != 200:
            logger.warning("GitHub search failed: %s %s", resp.status_code, resp.text[:200])
            return []

        data = resp.json()
        items = data.get("items", [])

    except httpx.TimeoutException:
        logger.warning("GitHub search timed out for query: %s", query)
        return []
    except Exception as e:
        logger.warning("GitHub search error: %s", e)
        return []

    results = []
    for repo in items:
        stars = repo.get("stargazers_count", 0)
        if stars < min_stars:
            continue

        pushed_at = repo.get("pushed_at", "")
        if pushed_at:
            try:
                pushed_dt = datetime.fromisoformat(pushed_at.replace("Z", "+00:00"))
                if pushed_dt < cutoff:
                    continue
            except (ValueError, TypeError):
                pass

        results.append({
            "name": repo.get("full_name", repo.get("name", "")),
            "url": repo.get("html_url", ""),
            "stars": stars,
            "description": (repo.get("description") or "")[:300],
            "last_updated": pushed_at[:10] if pushed_at else "unknown",
            "language": repo.get("language", "Python"),
            "topics": repo.get("topics", []),
        })

        if len(results) >= 10:
            break

    return results


# ─── 2. AI 策略摘要 ─────────────────────────────────────────────────────────────

def ai_summarize_strategy(repo_info: dict) -> dict:
    """
    用 AI 分析一个 GitHub 策略仓库，返回结构化摘要。

    Args:
        repo_info: search_github_strategies 返回的单条结果

    Returns:
        {
            name, url, stars,
            summary_cn, expected_annual_return, expected_max_drawdown,
            best_market, risks, ai_provider
        }
    """
    name = repo_info.get("name", "unknown")
    desc = repo_info.get("description", "无描述")
    stars = repo_info.get("stars", 0)
    topics = ", ".join(repo_info.get("topics", []))

    prompt = f"""你是一名量化交易专家。请分析以下 GitHub 交易策略仓库，用**中文**简洁回答。

仓库名称：{name}
描述：{desc}
Star 数：{stars}
标签：{topics}

请用 JSON 格式回答以下问题：
{{
  "summary_cn": "这个策略做什么（2-3句话，中文）",
  "strategy_type": "momentum/mean_reversion/arbitrage/ml_based/option_selling/other",
  "expected_annual_return_min": 数字（百分比，如 15 表示 15%）,
  "expected_annual_return_max": 数字,
  "expected_max_drawdown_min": 数字,
  "expected_max_drawdown_max": 数字,
  "best_market": "最适合的市场环境（1句话）",
  "risks": "主要风险（1-2句话）",
  "instruments": ["stock", "etf", "crypto", "options"]中适用的,
  "holding_period": "seconds/minutes/hours/days/weeks/months"
}}

只输出 JSON，不要其他文字。基于仓库描述和常识做出合理估计。"""

    raw = _call_ai(prompt, max_tokens=800)
    if not raw:
        return {
            **repo_info,
            "summary_cn": "AI 不可用，无法生成摘要",
            "expected_annual_return": [0, 0],
            "expected_max_drawdown": [0, 0],
            "best_market": "未知",
            "risks": "未知",
            "ai_provider": None,
        }

    try:
        text = raw.strip()
        start = text.find("{")
        end = text.rfind("}") + 1
        if start == -1 or end == 0:
            raise ValueError("No JSON found")
        parsed = json.loads(text[start:end])
    except (json.JSONDecodeError, ValueError):
        logger.warning("Failed to parse AI summary for %s", name)
        return {
            **repo_info,
            "summary_cn": raw[:500],
            "expected_annual_return": [0, 0],
            "expected_max_drawdown": [0, 0],
            "best_market": "见上方 AI 原始回复",
            "risks": "见上方 AI 原始回复",
            "ai_provider": "raw",
        }

    return {
        **repo_info,
        "summary_cn": parsed.get("summary_cn", ""),
        "strategy_type": parsed.get("strategy_type", "other"),
        "expected_annual_return": [
            parsed.get("expected_annual_return_min", 0),
            parsed.get("expected_annual_return_max", 0),
        ],
        "expected_max_drawdown": [
            parsed.get("expected_max_drawdown_min", 0),
            parsed.get("expected_max_drawdown_max", 0),
        ],
        "best_market": parsed.get("best_market", ""),
        "risks": parsed.get("risks", ""),
        "instruments": parsed.get("instruments", []),
        "holding_period": parsed.get("holding_period", "unknown"),
        "ai_provider": "ai",
    }


# ─── 3. AI 生成策略 ─────────────────────────────────────────────────────────────

def ai_generate_strategy(goals: dict) -> dict:
    """
    让 AI 根据用户目标生成一个交易策略。

    Args:
        goals: {
            "annual_return": 0.15,      # 目标年化收益 15%
            "max_drawdown": 0.10,       # 最大可接受回撤 10%
            "instruments": ["stock", "etf"],
            "holding_period": "days_to_weeks"
        }

    Returns:
        {
            strategy_name, description, logic_explanation,
            estimated_performance, python_signal_code, source
        }
    """
    annual_ret = goals.get("annual_return", 0.15)
    max_dd = goals.get("max_drawdown", 0.10)
    instruments = ", ".join(goals.get("instruments", ["stock"]))
    holding = goals.get("holding_period", "days_to_weeks")

    holding_cn = {
        "seconds": "秒级",
        "minutes": "分钟级",
        "hours": "小时级",
        "days": "日级",
        "days_to_weeks": "数天到数周",
        "weeks": "周级",
        "months": "月级",
    }.get(holding, holding)

    prompt = f"""你是一名量化交易策略开发专家。请根据以下约束条件设计一个完整的交易策略。

用户目标：
- 年化收益目标：{annual_ret * 100:.0f}%
- 最大可接受回撤：{max_dd * 100:.0f}%
- 交易工具：{instruments}
- 持仓周期：{holding_cn}

请用 JSON 格式输出：
{{
  "strategy_name": "策略名称（中文）",
  "strategy_id": "英文下划线slug",
  "description": "策略简介（2-3句中文）",
  "logic_explanation": "入场/出场/仓位管理的详细逻辑（中文，5-8句）",
  "entry_rules": ["入场条件1", "入场条件2"],
  "exit_rules": ["出场条件1", "出场条件2"],
  "risk_management": "风险管理方法（1-2句）",
  "estimated_annual_return": 数字百分比,
  "estimated_max_drawdown": 数字百分比,
  "estimated_win_rate": 数字百分比,
  "estimated_sharpe": 数字,
  "best_market": "最适合的市场环境",
  "worst_market": "最不适合的市场环境",
  "python_signal_code": "一段可运行的 Python 函数代码，输入 pandas DataFrame (columns: open, high, low, close, volume)，输出 signal 列 (1=买入, -1=卖出, 0=持有)"
}}

要求：
1. 策略必须在目标回撤范围内可行
2. python_signal_code 必须是可运行的真实代码，使用 pandas 和 numpy
3. 只输出 JSON，不要其他文字"""

    raw = _call_ai(prompt, max_tokens=2500)
    if not raw:
        return _fallback_strategy(goals)

    try:
        text = raw.strip()
        start = text.find("{")
        end = text.rfind("}") + 1
        if start == -1 or end == 0:
            raise ValueError("No JSON found")
        parsed = json.loads(text[start:end])
    except (json.JSONDecodeError, ValueError):
        logger.warning("Failed to parse AI generated strategy")
        return _fallback_strategy(goals)

    return {
        "strategy_name": parsed.get("strategy_name", "AI 生成策略"),
        "strategy_id": parsed.get("strategy_id", "ai_generated"),
        "description": parsed.get("description", ""),
        "logic_explanation": parsed.get("logic_explanation", ""),
        "entry_rules": parsed.get("entry_rules", []),
        "exit_rules": parsed.get("exit_rules", []),
        "risk_management": parsed.get("risk_management", ""),
        "estimated_performance": {
            "annual_return": parsed.get("estimated_annual_return", 0),
            "max_drawdown": parsed.get("estimated_max_drawdown", 0),
            "win_rate": parsed.get("estimated_win_rate", 0),
            "sharpe": parsed.get("estimated_sharpe", 0),
        },
        "best_market": parsed.get("best_market", ""),
        "worst_market": parsed.get("worst_market", ""),
        "python_signal_code": parsed.get("python_signal_code", ""),
        "source": "AI 生成",
        "instruments": goals.get("instruments", ["stock"]),
        "holding_period": holding,
    }


def _fallback_strategy(goals: dict) -> dict:
    """AI 不可用时返回一个基于 SMA 交叉的基础策略"""
    max_dd = goals.get("max_drawdown", 0.10)
    # 根据回撤容忍度调整止损
    stop_atr = 1.5 if max_dd <= 0.10 else 2.0 if max_dd <= 0.20 else 3.0

    return {
        "strategy_name": "SMA 均线交叉策略（保守型）",
        "strategy_id": "sma_crossover_conservative",
        "description": "基于 20/50 日均线交叉产生买卖信号，加入 ATR 动态止损控制回撤。",
        "logic_explanation": (
            "当 20 日均线从下方穿越 50 日均线时买入（金叉），"
            "当 20 日均线从上方穿越 50 日均线时卖出（死叉）。"
            f"同时设置 {stop_atr} 倍 ATR 动态止损保护本金。"
        ),
        "entry_rules": [
            "SMA(20) 上穿 SMA(50)（金叉）",
            "收盘价 > SMA(200)（确认上升趋势）",
        ],
        "exit_rules": [
            "SMA(20) 下穿 SMA(50)（死叉）",
            f"价格跌破入场价 - {stop_atr} × ATR（动态止损）",
        ],
        "risk_management": f"单笔仓位不超过总资金 5%，ATR {stop_atr}倍止损",
        "estimated_performance": {
            "annual_return": 12,
            "max_drawdown": max_dd * 100,
            "win_rate": 55,
            "sharpe": 0.8,
        },
        "best_market": "趋势明确的上涨行情",
        "worst_market": "长期横盘震荡行情",
        "python_signal_code": (
            "import pandas as pd\n"
            "import numpy as np\n\n"
            "def generate_signals(df):\n"
            "    df['sma_20'] = df['close'].rolling(20).mean()\n"
            "    df['sma_50'] = df['close'].rolling(50).mean()\n"
            "    df['signal'] = 0\n"
            "    df.loc[df['sma_20'] > df['sma_50'], 'signal'] = 1\n"
            "    df.loc[df['sma_20'] < df['sma_50'], 'signal'] = -1\n"
            "    return df\n"
        ),
        "source": "内置默认",
        "instruments": goals.get("instruments", ["stock"]),
        "holding_period": goals.get("holding_period", "days_to_weeks"),
    }


# ─── 4. 匹配评分 ─────────────────────────────────────────────────────────────────

def compute_match_score(strategy_info: dict, goals: dict) -> float:
    """
    计算策略与用户目标的匹配度。

    评分维度（满分 100）：
    - 年化收益匹配：40 分
    - 回撤匹配：30 分
    - 工具匹配：15 分
    - 持仓周期匹配：15 分

    Args:
        strategy_info: 包含 estimated_performance 或 expected_annual_return 的策略信息
        goals: 用户目标 dict

    Returns:
        0-100 的匹配百分比
    """
    score = 0.0
    target_return = goals.get("annual_return", 0.15) * 100  # 转换为百分比
    target_dd = goals.get("max_drawdown", 0.10) * 100
    target_instruments = set(goals.get("instruments", ["stock"]))
    target_holding = goals.get("holding_period", "days_to_weeks")

    # --- 收益匹配（40 分）---
    perf = strategy_info.get("estimated_performance", {})
    if perf:
        est_return = perf.get("annual_return", 0)
    else:
        # 从 expected_annual_return 范围取中间值
        ret_range = strategy_info.get("expected_annual_return", [0, 0])
        if isinstance(ret_range, list) and len(ret_range) == 2:
            est_return = (ret_range[0] + ret_range[1]) / 2
        else:
            est_return = 0

    if target_return > 0 and est_return > 0:
        ratio = est_return / target_return
        if ratio >= 1.0:
            # 满足或超过目标
            score += 40.0
        elif ratio >= 0.7:
            # 接近目标
            score += 40.0 * (ratio - 0.3) / 0.7
        else:
            score += 40.0 * ratio * 0.5

    # --- 回撤匹配（30 分）---
    if perf:
        est_dd = perf.get("max_drawdown", 0)
    else:
        dd_range = strategy_info.get("expected_max_drawdown", [0, 0])
        if isinstance(dd_range, list) and len(dd_range) == 2:
            est_dd = (dd_range[0] + dd_range[1]) / 2
        else:
            est_dd = 0

    if target_dd > 0 and est_dd > 0:
        if est_dd <= target_dd:
            # 回撤在目标内 — 满分
            score += 30.0
        elif est_dd <= target_dd * 1.5:
            # 略超目标
            overshoot = (est_dd - target_dd) / (target_dd * 0.5)
            score += 30.0 * (1 - overshoot)
        else:
            # 回撤远超目标
            score += 5.0

    # --- 工具匹配（15 分）---
    strategy_instruments = set(strategy_info.get("instruments", []))
    if not strategy_instruments:
        # 未知 — 给一半分
        score += 7.5
    elif target_instruments & strategy_instruments:
        overlap = len(target_instruments & strategy_instruments)
        total = len(target_instruments | strategy_instruments)
        score += 15.0 * overlap / total
    # else: 完全不匹配 — 0 分

    # --- 持仓周期匹配（15 分）---
    strategy_holding = strategy_info.get("holding_period", "unknown")
    holding_scores = _holding_period_similarity(target_holding, strategy_holding)
    score += 15.0 * holding_scores

    return round(min(max(score, 0), 100), 1)


def _holding_period_similarity(target: str, actual: str) -> float:
    """计算持仓周期相似度 0-1"""
    if actual == "unknown" or target == "unknown":
        return 0.5  # 未知给中间分

    # 定义顺序尺度
    scale = ["seconds", "minutes", "hours", "days", "days_to_weeks", "weeks", "months"]
    try:
        t_idx = scale.index(target)
    except ValueError:
        t_idx = 4  # default to days_to_weeks
    try:
        a_idx = scale.index(actual)
    except ValueError:
        a_idx = 4

    distance = abs(t_idx - a_idx)
    if distance == 0:
        return 1.0
    elif distance == 1:
        return 0.7
    elif distance == 2:
        return 0.4
    else:
        return 0.1


# ─── 5. 主入口：策略猎手 ──────────────────────────────────────────────────────────

async def hunt_strategies(goals: dict) -> list[dict]:
    """
    策略猎手主入口：搜索 GitHub + AI 摘要 + AI 生成 + 评分排序。

    Args:
        goals: {
            "annual_return": 0.15,
            "max_drawdown": 0.10,
            "instruments": ["stock", "etf"],
            "holding_period": "days_to_weeks",
            "search_query": "optional custom query"
        }

    Returns:
        按 match_score 降序排列的策略列表，每项包含完整信息和评分
    """
    all_strategies = []

    # --- Part A: GitHub 搜索 + AI 摘要 ---
    query = goals.get("search_query", "")
    if not query:
        # 根据用户目标生成搜索词
        instruments = goals.get("instruments", ["stock"])
        query_parts = ["trading strategy python"]
        if "crypto" in instruments:
            query_parts.append("crypto")
        if "options" in instruments:
            query_parts.append("options")
        if goals.get("holding_period") in ("seconds", "minutes", "hours"):
            query_parts.append("high frequency")
        query = " ".join(query_parts)

    repos = search_github_strategies(query, min_stars=10)
    logger.info("GitHub search returned %d repos for '%s'", len(repos), query)

    # AI 摘要（只对前 5 个做，避免太慢/太多 API 调用）
    for repo in repos[:5]:
        summary = ai_summarize_strategy(repo)
        summary["match_score"] = compute_match_score(summary, goals)
        summary["source"] = "GitHub"
        all_strategies.append(summary)

    # 未做 AI 摘要的仓库也加入（基础信息）
    for repo in repos[5:]:
        repo["match_score"] = 0.0  # 没有足够信息评分
        repo["source"] = "GitHub (未分析)"
        repo["summary_cn"] = repo.get("description", "")
        all_strategies.append(repo)

    # --- Part B: AI 生成定制策略 ---
    generated = ai_generate_strategy(goals)
    generated["match_score"] = compute_match_score(generated, goals)
    # AI 生成的策略天然匹配度高，但加个标记区分
    generated["source"] = "AI 生成"
    all_strategies.append(generated)

    # --- Part C: 本地策略库匹配 ---
    try:
        from strategy_library import filter_library
        lib_strategies = filter_library()
        for s in lib_strategies[:10]:
            entry = {
                "strategy_name": s.get("name", ""),
                "strategy_id": s.get("id", ""),
                "description": s.get("description", ""),
                "summary_cn": s.get("description", ""),
                "estimated_performance": {
                    "annual_return": (
                        (s.get("annual_return_range", [0, 0])[0]
                         + s.get("annual_return_range", [0, 0])[1]) / 2
                    ),
                    "max_drawdown": 15,  # 策略库默认估计
                    "win_rate": s.get("win_rate_pct", 0),
                    "sharpe": 0,
                },
                "instruments": [s.get("instrument", "stock")],
                "holding_period": "days_to_weeks",
                "best_market": s.get("best_market", ""),
                "worst_market": s.get("worst_market", ""),
                "risks": s.get("worst_market", ""),
                "source": "本地策略库",
                "tags": s.get("tags", []),
            }
            entry["match_score"] = compute_match_score(entry, goals)
            all_strategies.append(entry)
    except Exception as e:
        logger.warning("Failed to load local strategy library: %s", e)

    # --- 排序：match_score 降序 ---
    all_strategies.sort(key=lambda x: x.get("match_score", 0), reverse=True)

    return all_strategies
