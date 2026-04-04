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

def _call_ai(prompt: str, max_tokens: int = 2000):
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

def ai_generate_strategies(goals: dict, count: int = None) -> list:
    """一次调用 AI 生成尽可能多的风格各异策略，返回列表。count 为 None 时让 AI 自行决定数量。"""
    annual_ret = goals.get("annual_return", 0.15)
    max_dd = goals.get("max_drawdown", None)
    instruments = ", ".join(goals.get("instruments", ["stock"]))
    holding = goals.get("holding_period", "days_to_weeks")

    holding_cn = {
        "seconds": "秒级", "minutes": "分钟级", "hours": "小时级",
        "days": "日级", "days_to_weeks": "数天到数周",
        "weeks": "周级", "months": "月级",
    }.get(holding, holding)

    count_instruction = f"生成 {count} 个" if count else "尽可能多地生成符合目标的（上限不超过12个，若目标较难匹配也可以少于5个）"

    prompt = f"""你是量化交易策略专家。请根据以下目标，{count_instruction}风格各异的交易策略。

用户目标：
- 年化收益目标：{annual_ret * 100:.0f}%
- 最大可接受回撤：{f"{max_dd * 100:.0f}%" if max_dd is not None else "不设限制"}
- 交易工具：{instruments}
- 持仓周期：{holding_cn}

请尽量覆盖不同策略风格，如：动量/趋势跟踪、均值回归、突破/波动率、因子选股、宏观轮动、套利/对冲等。

请输出一个 JSON 数组，每个对象格式如下：
{{
  "strategy_name": "策略名称（中文，含风格关键词）",
  "strategy_id": "英文下划线slug_唯一",
  "description": "策略简介（2-3句中文）",
  "entry_rules": ["入场条件1", "入场条件2"],
  "exit_rules": ["出场条件1", "出场条件2"],
  "estimated_annual_return": 数字（百分比，如300表示300%）,
  "estimated_max_drawdown": 数字（百分比，如25表示25%）,
  "estimated_win_rate": 数字（百分比，如45表示45%）,
  "best_market": "最适合的市场环境（一句话）"
}}

要求：
1. 每个策略风格必须明显不同，不能雷同
2. 每个策略的 strategy_id 必须唯一
3. 只输出 JSON 数组 [...], 不要其他文字"""

    raw = _call_ai(prompt, max_tokens=4000)
    if not raw:
        logger.warning("ai_generate_strategies: AI returned empty response")
        return []

    try:
        text = raw.strip()
        # Strip markdown code blocks if present
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
        start = text.find("[")
        end = text.rfind("]") + 1
        if start == -1 or end == 0:
            logger.warning("ai_generate_strategies: no JSON array found. Raw (first 300): %s", raw[:300])
            raise ValueError("No JSON array found")
        parsed_list = json.loads(text[start:end])
        if not isinstance(parsed_list, list):
            raise ValueError("Not a list")
    except (json.JSONDecodeError, ValueError) as e:
        logger.warning("Failed to parse AI generated strategies batch: %s | raw (first 300): %s", e, raw[:300])
        return []

    results = []
    for p in parsed_list:
        _est_ret = p.get("estimated_annual_return", 0) or 0
        _est_dd = p.get("estimated_max_drawdown", 0) or 0
        results.append({
            "name": p.get("strategy_name", "AI 生成策略"),
            "id": p.get("strategy_id", "ai_generated"),
            "description": p.get("description", ""),
            "entry_rules": p.get("entry_rules", []),
            "exit_rules": p.get("exit_rules", []),
            "annual_return_range": [max(0, int(_est_ret * 0.8)), int(_est_ret * 1.2)] if _est_ret else [0, 0],
            "max_drawdown_range": [max(0, int(_est_dd * 0.8)), int(_est_dd * 1.2)] if _est_dd else None,
            "win_rate_pct": p.get("estimated_win_rate", 0),
            "best_market": p.get("best_market", ""),
            "source": "AI 生成",
            "instrument": "stock",
        })
    return results


def ai_generate_strategy(goals: dict) -> dict:
    """兼容旧调用，生成单个策略。"""
    results = ai_generate_strategies(goals, count=1)
    return results[0] if results else None


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


# ─── 3b. AI 代码生成 ──────────────────────────────────────────────────────────────

def generate_strategy_code(strategy_id: str, strategy_name: str, description: str,
                            style: str = "momentum", default_symbols: list = None) -> bool:
    """
    让 AI 为 autoresearch 生成的策略写出真实 Python 回测代码，
    写入 strategies/<strategy_id>.py，动态注册到 STRATEGY_REGISTRY。
    成功返回 True，失败返回 False。
    """
    import re
    import importlib.util
    import sys

    from strategies.base import get_strategy
    # 如果已经有实现就跳过
    if get_strategy(strategy_id):
        return True

    safe_id = re.sub(r"[^a-z0-9_]", "_", strategy_id.lower())[:40]
    # 类名：snake_case → CamelCase
    class_name = "".join(w.capitalize() for w in safe_id.split("_"))

    symbols_hint = ", ".join(default_symbols or ["SPY"])

    prompt = f"""你是量化策略开发专家。请为以下策略生成完整可运行的 Python 代码。

策略名称：{strategy_name}
策略风格：{style}
策略描述：{description}
默认标的：{symbols_hint}

严格按照以下模板生成，不要修改模板结构，只填充 generate_signals 方法内部逻辑：

```python
import pandas as pd
from strategies.base import StrategyBase, Signal, register_strategy


@register_strategy
class {class_name}(StrategyBase):
    name = "{safe_id}"
    description = "{strategy_name}"
    default_params = {{
        # 在此填写策略参数，例如 "period": 14, "threshold": 0.5
    }}

    def generate_signals(self, df: pd.DataFrame) -> list[Signal]:
        signals = []
        # df 包含列：open, high, low, close, volume
        # 可用指标列（已预计算）：sma_20, sma_50, sma_200, ema_12, ema_26,
        #   rsi_14, macd, macd_signal, bb_upper, bb_lower, atr_14
        # 用 df.get("col_name") 获取，可能为 None
        #
        # 在此编写信号生成逻辑：
        # 买入信号：signals.append(Signal(timestamp=..., symbol="", direction="long", entry_price=..., stop_loss=..., strategy_name=self.name))
        # 平仓信号：signals.append(Signal(timestamp=..., symbol="", direction="close", entry_price=..., strategy_name=self.name))

        # ── 在此实现 {strategy_name} 的核心逻辑 ──

        return signals
```

要求：
1. 完全按照模板，不要更改类名 {class_name}、name="{safe_id}"
2. generate_signals 必须遍历 df 行，生成 Signal 列表
3. 只使用 pandas/numpy，不要 import 其他库（ta 库除外，用 ta.xxx 即可）
4. 必须维护 position_open 变量，防止重复开仓
5. 只输出 Python 代码，不要其他文字，不要 markdown 代码块标记
"""

    raw = _call_ai(prompt, max_tokens=2000)
    if not raw:
        logger.warning("generate_strategy_code: AI returned empty for %s", strategy_id)
        return False

    # Strip markdown code fences
    code = raw.strip()
    if code.startswith("```"):
        lines = code.split("\n")
        code = "\n".join(l for l in lines if not l.strip().startswith("```"))

    # Validate syntax
    try:
        compile(code, f"<{safe_id}>", "exec")
    except SyntaxError as e:
        logger.warning("generate_strategy_code: syntax error for %s: %s", safe_id, e)
        return False

    # Write to strategies directory
    strategies_dir = os.path.join(os.path.dirname(__file__), "strategies")
    file_path = os.path.join(strategies_dir, f"{safe_id}.py")
    try:
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(f'"""\nAI 生成策略: {strategy_name}\n自动生成，勿手动编辑\n"""\n')
            f.write(code)
    except Exception as e:
        logger.warning("generate_strategy_code: write failed for %s: %s", safe_id, e)
        return False

    # Dynamically import and register
    try:
        spec = importlib.util.spec_from_file_location(f"strategies.{safe_id}", file_path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[f"strategies.{safe_id}"] = module
        spec.loader.exec_module(module)
        logger.info("generate_strategy_code: registered %s successfully", safe_id)
        return True
    except Exception as e:
        logger.warning("generate_strategy_code: import failed for %s: %s", safe_id, e)
        # Clean up bad file
        try:
            os.remove(file_path)
        except Exception:
            pass
        return False


# ─── 3c. 快速回测 + 真实评分 ────────────────────────────────────────────────────────

def quick_backtest_strategy(safe_id: str, symbol: str = "SPY", lookback_years: int = 2) -> dict | None:
    """
    用注册的 StrategyBase 类跑 2 年真实回测，返回实测指标。
    这是 Karpathy autoresearch 范式的"eval"步骤。
    """
    from datetime import datetime, timedelta
    from market_data import fetch_stock_history, compute_technicals
    from backtester import _simulate_portfolio, COST_MODELS
    from strategies.base import get_strategy

    strategy_cls = get_strategy(safe_id)
    if not strategy_cls:
        return None

    start = (datetime.now() - timedelta(days=lookback_years * 365)).strftime("%Y-%m-%d")
    df = fetch_stock_history(symbol, start=start)
    if df is None or df.empty or len(df) < 50:
        return None

    df = compute_technicals(df)
    try:
        strategy = strategy_cls({})
        signals = strategy.generate_signals(df)
        for s in signals:
            s.symbol = symbol

        metrics = _simulate_portfolio(
            signals, df, risk_per_trade=0.02, cost_model=COST_MODELS["default"]
        )

        total_ret = metrics.total_return  # fraction
        annual_ret = ((1 + total_ret) ** (1 / lookback_years) - 1) * 100

        return {
            "sharpe": round(metrics.sharpe_ratio, 2),
            "total_return": round(total_ret * 100, 1),
            "annual_return": round(annual_ret, 1),
            "max_drawdown": round(abs(metrics.max_drawdown) * 100, 1),
            "total_trades": metrics.total_trades,
            "symbol": symbol,
        }
    except Exception as e:
        logger.warning("quick_backtest_strategy failed for %s: %s", safe_id, e)
        return None


def score_vs_goals(bt_metrics: dict, goals: dict) -> float:
    """
    基于真实回测指标计算策略与目标的匹配分 (0–100)。
    Sharpe 30分 + 年化收益 40分 + 回撤控制 30分。
    """
    score = 0.0

    # Sharpe (30分): ≥1.0 满分, <0 得 0
    sharpe = bt_metrics.get("sharpe", 0) or 0
    score += min(30.0, max(0.0, sharpe * 30.0))

    # 年化收益 (40分)
    target_return = (goals.get("annual_return") or 0.15) * 100
    actual_annual = bt_metrics.get("annual_return", 0) or 0
    if target_return > 0:
        ratio = actual_annual / target_return
        score += min(40.0, max(0.0, ratio * 40.0))
    else:
        score += 40.0

    # 最大回撤 (30分): 不超目标满分，超出按比例扣
    max_dd_limit = (goals.get("max_drawdown") or 0.20) * 100
    actual_dd = bt_metrics.get("max_drawdown", 100) or 100
    if actual_dd <= max_dd_limit:
        score += 30.0
    elif actual_dd <= max_dd_limit * 2:
        overshoot = (actual_dd - max_dd_limit) / max_dd_limit
        score += max(0.0, 30.0 * (1 - overshoot))

    return round(min(100.0, max(0.0, score)), 1)


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
    _annual = goals.get("annual_return")   # None = 不设收益上限
    _drawdown = goals.get("max_drawdown")  # None = 不设回撤下限
    target_return = (_annual * 100) if _annual is not None else None
    target_dd = (_drawdown * 100) if _drawdown is not None else None
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

    if target_return is None:
        # 不设收益上限：所有策略满分
        score += 40.0
    elif target_return > 0 and est_return > 0:
        ratio = est_return / target_return
        if ratio >= 1.0:
            score += 40.0
        elif ratio >= 0.7:
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

    if target_dd is None:
        # 不设回撤下限：所有策略满分
        score += 30.0
    elif target_dd > 0 and est_dd > 0:
        if est_dd <= target_dd:
            score += 30.0
        elif est_dd <= target_dd * 1.5:
            overshoot = (est_dd - target_dd) / (target_dd * 0.5)
            score += 30.0 * (1 - overshoot)
        else:
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


# ─── 后台研究引擎 ─────────────────────────────────────────────────────────────────

def _call_ai_with_provider(prompt: str, provider: str, max_tokens: int = 2000):
    """调用指定 provider 的 AI，不走 get_active_provider() 自动选择"""
    from ai_analysis import AI_PROVIDERS, _call_openai_compatible, _call_claude, _call_gemini
    if provider not in AI_PROVIDERS:
        return _call_ai(prompt, max_tokens)
    cfg = AI_PROVIDERS[provider]
    key = os.getenv(cfg["env_key"])
    if not key:
        return _call_ai(prompt, max_tokens)
    try:
        if provider in ("deepseek", "openai", "xai"):
            result = _call_openai_compatible(cfg["base_url"], key, cfg["model"], prompt, provider)
        elif provider == "claude":
            result = _call_claude(key, cfg["model"], prompt)
        elif provider == "gemini":
            result = _call_gemini(key, cfg["model"], prompt)
        else:
            return None
        return result.get("analysis")
    except Exception as e:
        logger.warning("Research AI call failed (%s): %s", provider, e)
        return None


def _ai_generate_with_provider(goals: dict, provider: str, iteration: int = 1):
    """与 ai_generate_strategy 相同但使用指定 provider，并要求生成不同类型策略"""
    annual_ret = goals.get("annual_return", 0.15)
    max_dd = goals.get("max_drawdown", 0.10)
    instruments = ", ".join(goals.get("asset_classes", "us_stocks,etf").split(","))

    # 每轮要求不同风格，避免重复
    styles = ["momentum", "mean_reversion", "volatility", "options_selling", "trend_following"]
    style = styles[(iteration - 1) % len(styles)]

    prompt = f"""你是量化交易策略研究专家。这是第{iteration}轮研究，请生成一个【{style}】风格的交易策略。

用户目标：年化{annual_ret*100:.0f}%，最大回撤≤{max_dd*100:.0f}%，交易品种：{instruments}

严格输出 JSON，字段：
{{
  "id": "英文snake_case唯一ID",
  "name": "中文策略名",
  "description": "2-3句中文描述",
  "source": "AI Research R{iteration}",
  "instrument": "stock/etf/option之一",
  "direction": "bullish/bearish/neutral之一",
  "style": "{style}",
  "risk_level": "low/medium/high之一",
  "annual_return_range": [最小年化%, 最大年化%],
  "win_rate_pct": 胜率数字,
  "params": {{"param1": value1}},
  "tags": ["标签1", "标签2"],
  "why_it_works": "原理解释（2句）",
  "best_market": "最适合市场条件",
  "worst_market": "最不适合市场条件",
  "default_symbols": ["TICKER1", "TICKER2"]
}}

只输出JSON。"""

    raw = _call_ai_with_provider(prompt, provider, max_tokens=1500)
    if not raw:
        return None
    try:
        text = raw.strip()
        start = text.find("{")
        end = text.rfind("}") + 1
        if start == -1 or end == 0:
            return None
        parsed = json.loads(text[start:end])
        parsed["source"] = f"AI Research R{iteration}"
        return parsed
    except Exception:
        return None


def run_research_job(job_id: int, goals_dict: dict, preferred_model: str) -> None:
    """
    后台研究主函数 — 基于 Karpathy autoresearch 范式。

    核心循环（autoresearch loop）：
      LOOP N 次：
        1. 生成假设（新策略）
        2. 评分（compute_match_score = 量化指标）
        3. 分数 ≥ KEEP_THRESHOLD → KEEP（加入结果集）
           否则 → DISCARD，并记录原因
        4. 若本轮有留下的策略 → 下轮让 AI 在最优结果基础上改进
           否则 → 换风格重新探索

    结合 GitHub 搜索作为初始化种子，AI 迭代研究不断优化。
    """
    from models import SessionLocal, ResearchJob
    db = SessionLocal()

    KEEP_THRESHOLD = 40   # 分数阈值：≥40 才 KEEP（与 hunt_search 一致）
    MAX_ITERATIONS = 10   # autoresearch 轮数（Karpathy 模式：迭代越多越好）

    def _save(job):
        job.updated_at = datetime.now()
        db.commit()

    def _log(job, msg: str, step_type: str = "info"):
        steps = json.loads(job.steps_log or "[]")
        steps.append({"time": datetime.now().strftime("%H:%M:%S"), "msg": msg, "type": step_type})
        job.steps_log = json.dumps(steps, ensure_ascii=False)
        _save(job)

    def _push_strategy(job, strategy, all_strategies):
        """将策略加入结果集并持久化"""
        all_strategies.append(strategy)
        all_strategies.sort(key=lambda x: x.get("match_pct", 0), reverse=True)
        job.strategies_found = json.dumps(all_strategies, ensure_ascii=False, default=str)
        job.total_found = len(all_strategies)
        _save(job)

    try:
        job = db.query(ResearchJob).filter(ResearchJob.id == job_id).first()
        if not job:
            return
        job.status = "running"
        job.model_used = preferred_model
        _save(job)

        all_strategies = []
        best_score_so_far = 0.0
        best_strategy_so_far = None
        discard_history = []  # Karpathy 模式：记录失败方向，避免重蹈覆辙

        # ══ Phase 0: GitHub 种子搜索 ══════════════════════════════════
        _log(job, "🌐 [Phase 0] GitHub 量化策略库种子搜索...", "progress")
        try:
            query = "quantitative trading strategy python"
            if "crypto" in goals_dict.get("asset_classes", ""):
                query = "crypto trading bot python strategy"
            elif "options" in goals_dict.get("asset_classes", ""):
                query = "options trading strategy python sell put"
            repos = search_github_strategies(query, min_stars=100)
            if repos:
                _log(job, f"✅ GitHub 找到 {len(repos)} 个仓库，摘要分析中...", "success")
                for repo in repos[:3]:
                    try:
                        summary = ai_summarize_strategy(repo)
                        strategy = {
                            "id": summary.get("name", "").replace("/", "_").replace(" ", "_").lower()[:40],
                            "name": summary.get("name", "GitHub策略"),
                            "description": summary.get("summary_cn", summary.get("description", "")),
                            "source": f"GitHub ⭐{summary.get('stars', 0)}",
                            "url": summary.get("url", ""),
                            "instrument": "stock",
                            "direction": "bullish",
                            "style": summary.get("strategy_type", "other"),
                            "risk_level": "medium",
                            "annual_return_range": summary.get("expected_annual_return", [10, 20]),
                            "win_rate_pct": 50,
                            "tags": (summary.get("instruments", []) + summary.get("topics", []))[:4],
                            "why_it_works": summary.get("summary_cn", ""),
                            "best_market": summary.get("best_market", ""),
                            "worst_market": summary.get("risks", ""),
                            "default_symbols": ["SPY", "QQQ"],
                        }
                        score = compute_match_score(strategy, goals_dict)
                        strategy["match_pct"] = round(score)
                        if score >= KEEP_THRESHOLD:
                            _log(job, f"  KEEP ✅ {strategy['name']} (分数={round(score)})", "success")
                            _push_strategy(job, strategy, all_strategies)
                            if score > best_score_so_far:
                                best_score_so_far = score
                                best_strategy_so_far = strategy
                        else:
                            _log(job, f"  DISCARD ✗ {strategy['name']} (分数={round(score)}<{KEEP_THRESHOLD})", "warn")
                    except Exception:
                        continue
            else:
                _log(job, "⚠️ GitHub 受限，跳过种子搜索", "warn")
        except Exception as e:
            _log(job, f"⚠️ GitHub 阶段异常: {e}", "warn")

        # ══ Phase 1+: Autoresearch 迭代循环 ═══════════════════════════
        styles = ["momentum", "mean_reversion", "volatility_breakout", "options_selling", "trend_following"]

        for iteration in range(1, MAX_ITERATIONS + 1):
            _log(job, f"─── [迭代 {iteration}/{MAX_ITERATIONS}] autoresearch 循环开始 ───", "progress")

            # 构造本轮 prompt：若有最优策略则让 AI 改进，否则换风格探索
            style = styles[(iteration - 1) % len(styles)]
            # Karpathy 模式：处理 None 目标值（不设限 = 用保守默认值）
            annual_ret = goals_dict.get("annual_return") or 0.15
            max_dd = goals_dict.get("max_drawdown") or 0.20
            goal_return_str = f"年化{annual_ret*100:.0f}%" if goals_dict.get("annual_return") is not None else "年化不设上限"
            goal_dd_str = f"最大回撤≤{max_dd*100:.0f}%" if goals_dict.get("max_drawdown") is not None else "回撤不设下限"

            # Karpathy 模式：构建失败历史文本，避免 AI 重蹈覆辙
            discard_text = ""
            if discard_history:
                lines = [f"  - 第{d['iteration']}轮 {d['style']}风格: {d['name']}, 分数={d['score']}, 问题: {d['reason']}" for d in discard_history[-5:]]
                discard_text = "\n\n⚠️ 之前被丢弃的方向（请避开这些方向或解决其问题）：\n" + "\n".join(lines)

            if best_strategy_so_far and iteration > 1:
                # 改进模式：基于最优策略变体 + 失败历史
                best_name = best_strategy_so_far.get("name", "")
                best_desc = best_strategy_so_far.get("description", "")
                best_validation = best_strategy_so_far.get("_validation_summary", "")
                prompt = f"""你是量化策略研究专家，进行第{iteration}轮 autoresearch 迭代。

当前最优策略（分数={round(best_score_so_far)}）：
名称：{best_name}
描述：{best_desc}
{f"回测验证: {best_validation}" if best_validation else ""}

用户目标：{goal_return_str}，{goal_dd_str}
{discard_text}

请生成一个【改进版本或互补策略】，要求：
1. 解决上述策略的主要缺点
2. 或从不同角度（{style}风格）达到同样目标
3. 必须比上述策略有更好的风险调整收益
4. 简洁优先原则：同等效果下，策略逻辑越简洁越好。删除不必要的复杂度本身就是一种改进。

严格输出 JSON：
{{
  "id": "唯一英文snake_case",
  "name": "中文名称",
  "description": "2-3句中文描述",
  "source": "AI Autoresearch R{iteration}",
  "instrument": "stock/etf/option之一",
  "direction": "bullish/bearish/neutral之一",
  "style": "{style}",
  "risk_level": "low/medium/high",
  "annual_return_range": [最小%, 最大%],
  "win_rate_pct": 胜率数字,
  "params": {{}},
  "tags": ["tag1","tag2"],
  "why_it_works": "原理2句",
  "best_market": "适合市场",
  "worst_market": "不适合市场",
  "default_symbols": ["TICKER1"]
}}
只输出JSON。"""
            else:
                # 探索模式：全新风格 + 失败历史
                prompt = f"""你是量化策略研究专家，进行第{iteration}轮探索，风格：{style}。

用户目标：{goal_return_str}，{goal_dd_str}
{discard_text}

请设计一个经过深思熟虑的【{style}】风格策略。
简洁优先原则：同等效果下，策略逻辑越简洁越好。

严格输出 JSON：
{{
  "id": "唯一英文snake_case",
  "name": "中文名称",
  "description": "2-3句中文描述",
  "source": "AI Autoresearch R{iteration}",
  "instrument": "stock/etf/option之一",
  "direction": "bullish/bearish/neutral之一",
  "style": "{style}",
  "risk_level": "low/medium/high",
  "annual_return_range": [最小%, 最大%],
  "win_rate_pct": 胜率数字,
  "params": {{}},
  "tags": ["tag1","tag2"],
  "why_it_works": "原理2句",
  "best_market": "适合市场",
  "worst_market": "不适合市场",
  "default_symbols": ["TICKER1"]
}}
只输出JSON。"""

            # ── 执行生成 + 评分 + keep/discard ──────────────────────
            try:
                raw = _call_ai_with_provider(prompt, preferred_model, max_tokens=1200)
                if not raw:
                    _log(job, f"  ⚠️ 第{iteration}轮 AI 无响应", "warn")
                    continue

                text = raw.strip()
                start = text.find("{")
                end = text.rfind("}") + 1
                if start == -1 or end == 0:
                    _log(job, f"  ⚠️ 第{iteration}轮 JSON 解析失败", "warn")
                    continue

                strategy = json.loads(text[start:end])

                # ── Karpathy autoresearch 核心：生成真实代码 → 运行真实回测 ──
                # 类比 train.py 修改 → 跑 5 分钟 → 测 val_bpb，我们是：
                #   生成 StrategyBase 类 → 跑 2 年回测 → 测 Sharpe/收益/回撤
                import re as _re
                safe_id = _re.sub(r"[^a-z0-9_]", "_", (strategy.get("id") or "ai_r").lower())[:40]
                test_symbol = (strategy.get("default_symbols") or ["SPY"])[0]

                _log(job, f"  🔧 [代码生成] {strategy.get('name','?')} → strategies/{safe_id}.py", "info")
                code_ok = generate_strategy_code(
                    strategy_id=safe_id,
                    strategy_name=strategy.get("name", "AI策略"),
                    description=strategy.get("description", ""),
                    style=style,
                    default_symbols=strategy.get("default_symbols", ["SPY"]),
                )

                bt_metrics = None
                if code_ok:
                    _log(job, f"  📊 [回测] {safe_id} × {test_symbol} (2年)...", "info")
                    bt_metrics = quick_backtest_strategy(safe_id, test_symbol)
                    if bt_metrics:
                        strategy["backtest_metrics"] = bt_metrics
                        strategy["validated"] = True
                        summary = (
                            f"Sharpe={bt_metrics['sharpe']}, "
                            f"年化={bt_metrics['annual_return']}%, "
                            f"回撤={bt_metrics['max_drawdown']}%, "
                            f"交易{bt_metrics['total_trades']}次"
                        )
                        strategy["_validation_summary"] = summary
                        _log(job, f"  📊 实测结果：{summary}", "info")
                    else:
                        _log(job, f"  ⚠️ 回测无结果（策略无信号或数据不足）", "warn")
                else:
                    _log(job, f"  ⚠️ 代码生成失败，跳过回测", "warn")

                # 评分：有真实回测用 score_vs_goals，否则 fallback 到假评分
                if bt_metrics:
                    score = score_vs_goals(bt_metrics, goals_dict)
                else:
                    score = compute_match_score(strategy, goals_dict)
                strategy["match_pct"] = round(score)

                # ── KEEP / DISCARD 决策（含回撤硬约束）──────────────
                dd_target_pct = (goals_dict.get("max_drawdown") or 1.0) * 100
                if bt_metrics:
                    strategy_dd = bt_metrics.get("max_drawdown")
                elif strategy.get("max_drawdown_range"):
                    strategy_dd = strategy["max_drawdown_range"][0]
                else:
                    strategy_dd = None

                dd_exceeded = strategy_dd is not None and strategy_dd > dd_target_pct

                if dd_exceeded:
                    _log(job, f"  DISCARD ✗ {strategy.get('name','?')} 回撤{strategy_dd}%>{dd_target_pct}% 超出目标", "warn")
                    reason = f"回撤{strategy_dd}%超出目标{dd_target_pct}%"
                elif score >= KEEP_THRESHOLD:
                    _log(job, f"  KEEP ✅ {strategy.get('name','?')} 分数={round(score)}", "success")
                    _push_strategy(job, strategy, all_strategies)
                    if score > best_score_so_far:
                        best_score_so_far = score
                        best_strategy_so_far = strategy
                        _log(job, f"  🏆 新最优！分数提升至 {round(score)}", "success")
                    continue
                else:
                    reason = "回撤超标" if (strategy_dd or 0) > dd_target_pct * 0.8 else "收益不达标" if score < 35 else "综合分数不足"
                    discard_history.append({
                        "iteration": iteration,
                        "style": style,
                        "name": strategy.get("name", "?"),
                        "score": round(score),
                        "reason": reason,
                    })
                    _log(job, f"  DISCARD ✗ 分数={round(score)}<{KEEP_THRESHOLD}，记录失败方向", "warn")

            except json.JSONDecodeError:
                _log(job, f"  ⚠️ 第{iteration}轮 JSON 格式错误", "warn")
            except Exception as e:
                _log(job, f"  ❌ 第{iteration}轮异常: {e}", "error")

        # ══ Phase Final：多资产组合构建（QuantEvolve 兜底）════════════
        # 若单一策略均未达标，让 AI 设计股票+期权组合，并用 portfolio_optimizer 优化权重
        if best_score_so_far < KEEP_THRESHOLD:
            annual_ret = goals_dict.get("annual_return") or 0.15
            max_dd = goals_dict.get("max_drawdown") or 0.20
            _log(job, "🔬 [Phase Final] 单资产无法达标，切换多资产+期权组合模式...", "progress")

            combo_prompt = f"""你是量化组合策略专家。单一资产策略无法同时达到年化{annual_ret*100:.0f}%且回撤≤{max_dd*100:.0f}%。

请设计一个【多资产+期权组合策略】，通过组合协同效应达到目标：

要求：
1. 核心持股（占60-80%）：2-4只股票/ETF，分散风险
2. 期权增益/保护层（占20-40%）：卖 Put 收权利金或保护性 Put
3. 整体组合预期：年化{annual_ret*100:.0f}%，最大回撤≤{max_dd*100:.0f}%
4. 每个成分需说明具体入场/出场规则

输出 JSON：
{{
  "id": "multi_asset_combo",
  "name": "多资产期权组合策略",
  "description": "2-3句中文描述整体策略",
  "components": [
    {{"asset": "SPY", "weight_pct": 40, "role": "核心趋势仓", "logic": "入场出场逻辑"}},
    {{"asset": "QQQ", "weight_pct": 30, "role": "成长增益仓", "logic": "入场出场逻辑"}},
    {{"asset": "SPY Put", "weight_pct": 20, "role": "期权保护层", "logic": "每月卖Put收权利金"}}
  ],
  "source": "AI 多资产组合",
  "instrument": "portfolio",
  "direction": "bullish",
  "style": "multi_asset_combo",
  "risk_level": "medium",
  "annual_return_range": [最小%, 最大%],
  "win_rate_pct": 胜率数字,
  "why_it_works": "组合协同原理",
  "best_market": "适合环境",
  "worst_market": "不适合环境",
  "default_symbols": ["SPY", "QQQ"],
  "tags": ["组合策略", "期权", "多资产"]
}}
只输出JSON。"""

            try:
                raw = _call_ai_with_provider(combo_prompt, preferred_model, max_tokens=1500)
                if raw:
                    text = raw.strip()
                    start = text.find("{")
                    end = text.rfind("}") + 1
                    if start != -1 and end > 0:
                        combo_strategy = json.loads(text[start:end])
                        combo_dd_range = combo_strategy.get("annual_return_range", [0, 100])  # fallback
                        # 检查 AI 声称的回撤是否超标
                        combo_dd_est = combo_strategy.get("max_drawdown_range", [0, 0])
                        if isinstance(combo_dd_est, list) and len(combo_dd_est) == 2:
                            combo_dd_low = combo_dd_est[0]
                        else:
                            combo_dd_low = 0
                        dd_limit = (goals_dict.get("max_drawdown") or 1.0) * 100
                        if combo_dd_low > dd_limit:
                            _log(job, f"  ✗ 多资产组合回撤{combo_dd_low}%>{dd_limit}%，不符合目标", "warn")
                        else:
                            score = compute_match_score(combo_strategy, goals_dict)
                            combo_strategy["match_pct"] = round(score)
                            combo_strategy["is_portfolio"] = True
                            _log(job, f"  ✅ 多资产组合策略生成，分数={round(score)}", "success")
                            _push_strategy(job, combo_strategy, all_strategies)
            except Exception as e:
                _log(job, f"  ⚠️ 多资产组合生成失败: {e}", "warn")

            # 用 portfolio_optimizer 构建科学权重的组合作为补充
            try:
                from portfolio_optimizer import build_portfolio_strategy
                _log(job, "  📐 portfolio_optimizer 构建权重优化组合...", "progress")
                port_strategy = build_portfolio_strategy(annual_ret, max_dd, period="2y")
                if port_strategy:
                    port_dd = port_strategy.get("max_drawdown_pct", 0)
                    dd_limit = (goals_dict.get("max_drawdown") or 1.0) * 100
                    if port_dd > dd_limit:
                        _log(job, f"  ✗ 权重优化组合回撤{port_dd}%>{dd_limit}%，不符合目标，丢弃", "warn")
                    else:
                        score = compute_match_score(port_strategy, goals_dict)
                        port_strategy["match_pct"] = round(score)
                        _log(job, f"  ✅ 权重优化组合：{port_strategy.get('method')}，回撤{port_dd}%，分数={round(score)}", "success")
                        _push_strategy(job, port_strategy, all_strategies)
            except Exception as e:
                _log(job, f"  ⚠️ portfolio_optimizer 失败: {e}", "warn")

        # ══ 完成 ═══════════════════════════════════════════════════════
        job.status = "completed"
        job.completed_at = datetime.now()
        _log(job, f"🎉 Autoresearch 完成！KEEP {len(all_strategies)} 个策略，最优分数={round(best_score_so_far)}", "done")

    except Exception as e:
        try:
            job = db.query(ResearchJob).filter(ResearchJob.id == job_id).first()
            if job:
                job.status = "failed"
                job.error = str(e)
                db.commit()
        except Exception:
            pass
        logger.error("ResearchJob %d crashed: %s", job_id, e)
    finally:
        db.close()
