"""
QuantPrism — 目标驱动投资组合优化器
集成 PyPortfolioOpt（有效前沿）+ Riskfolio-Lib（CDaR 回撤约束）

使用位置：
  - 策略猎手 Tier 2：单一策略无法满足目标时，构建多资产组合
  - /hunt/portfolio-optimize 端点：用户直接请求组合优化
  - combo_scorer.py：替换启发式权重分配

优先链：Riskfolio-Lib (CDaR约束最大化收益)
          → PyPortfolioOpt (有效前沿目标收益)
          → 等权重降级
"""

import logging
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


# ─── 候选资产池 ───────────────────────────────────────────────────────────────
# 根据收益/回撤目标动态选取

ASSET_POOLS = {
    "defensive": ["SPY", "QQQ", "GLD", "TLT", "IEF"],          # 低波动
    "core": ["SPY", "QQQ", "IWM", "GLD", "SCHD"],               # 核心多元
    "growth": ["AAPL", "MSFT", "NVDA", "AMZN", "META", "GOOGL"],# 成长股
    "income": ["O", "JEPI", "SCHD", "VYM"],                     # 派息
    "leveraged": ["TQQQ", "UPRO", "SOXL"],                      # 杠杆（高目标专用）
}


def _select_symbols(target_return: float, max_drawdown: float) -> list[str]:
    """根据目标动态选取候选资产，保守目标不含杠杆产品"""
    symbols = list(ASSET_POOLS["core"])

    if target_return >= 0.30:
        symbols += ASSET_POOLS["growth"]
    if target_return >= 0.50:
        symbols += ASSET_POOLS["leveraged"]
    if max_drawdown >= 0.15:
        symbols += ASSET_POOLS["growth"]
    if max_drawdown <= 0.10:
        # 严格低回撤：剔除杠杆
        symbols = [s for s in symbols if s not in ASSET_POOLS["leveraged"]]
        symbols += ASSET_POOLS["defensive"]

    return list(dict.fromkeys(symbols))  # 去重保序


def _fetch_prices(symbols: list[str], period: str = "3y") -> Optional[pd.DataFrame]:
    """获取历史收盘价，从 MarketDataCache 或 yfinance"""
    try:
        import yfinance as yf
        data = yf.download(
            symbols, period=period, progress=False,
            auto_adjust=True, threads=True
        )
        if data.empty:
            return None

        prices = data["Close"] if isinstance(data.columns, pd.MultiIndex) else data
        # 过滤数据缺失超过 20% 的股票
        prices = prices.dropna(axis=1, thresh=int(len(prices) * 0.8))
        prices = prices.dropna()
        return prices if len(prices.columns) >= 3 else None
    except Exception as e:
        logger.warning("价格数据获取失败: %s", e)
        return None


def _compute_portfolio_metrics(weights: dict, prices: pd.DataFrame) -> dict:
    """用真实价格数据计算组合年化收益和最大回撤"""
    returns = prices.pct_change().dropna()
    w = pd.Series(weights).reindex(prices.columns).fillna(0)
    port_ret = (returns * w).sum(axis=1)

    annual_return = (1 + port_ret.mean()) ** 252 - 1

    cum = (1 + port_ret).cumprod()
    rolling_max = cum.cummax()
    max_drawdown = float(abs(((cum - rolling_max) / rolling_max).min()))

    return {
        "annual_return_pct": round(annual_return * 100, 1),
        "max_drawdown_pct": round(max_drawdown * 100, 1),
    }


# ─── Riskfolio-Lib：CDaR 约束优化 ─────────────────────────────────────────────

def _optimize_riskfolio(prices: pd.DataFrame, target_return: float) -> Optional[dict]:
    """
    Riskfolio-Lib CDaR（条件回撤风险）优化。
    目标：最大化期望收益，控制最大回撤风险。
    """
    try:
        import riskfolio as rp

        returns = prices.pct_change().dropna()
        port = rp.Portfolio(returns=returns)
        port.assets_stats(method_mu="hist", method_cov="hist")

        # 先尝试 CDaR (Conditional Drawdown at Risk)
        w = port.optimization(
            model="Classic", rm="CDaR",
            obj="MaxRet", rf=0.05, l=0, hist=True,
        )

        if w is None or w.empty:
            # 降级到均值方差
            w = port.optimization(
                model="Classic", rm="MV",
                obj="Sharpe", rf=0.05, l=0, hist=True,
            )

        if w is None or w.empty:
            return None

        weights = {k: round(float(v), 4) for k, v in w["weights"].items() if v > 0.005}
        metrics = _compute_portfolio_metrics(weights, prices)

        return {
            "weights": weights,
            "method": "Riskfolio-CDaR",
            **metrics,
        }
    except ImportError:
        logger.info("Riskfolio-Lib 未安装，跳过 CDaR 优化")
        return None
    except Exception as e:
        logger.warning("Riskfolio 优化失败: %s", e)
        return None


# ─── PyPortfolioOpt：有效前沿优化 ─────────────────────────────────────────────

def _optimize_pypfopt(prices: pd.DataFrame, target_return: float) -> Optional[dict]:
    """
    PyPortfolioOpt 有效前沿：给定目标年化收益，最小化波动率。
    若目标不可达则自动退化为最大 Sharpe 组合。
    """
    try:
        from pypfopt import EfficientFrontier, expected_returns, risk_models

        mu = expected_returns.mean_historical_return(prices)
        S = risk_models.sample_cov(prices)
        ef = EfficientFrontier(mu, S)

        try:
            ef.efficient_return(target_return=target_return)
        except Exception:
            # 目标收益不可达 → 退化为最大 Sharpe
            ef = EfficientFrontier(mu, S)
            ef.max_sharpe(risk_free_rate=0.05)

        raw_weights = ef.clean_weights()
        weights = {k: round(v, 4) for k, v in raw_weights.items() if v > 0.01}

        perf = ef.portfolio_performance(verbose=False, risk_free_rate=0.05)
        metrics = _compute_portfolio_metrics(weights, prices)

        return {
            "weights": weights,
            "method": "PyPortfolioOpt-EF",
            "sharpe": round(float(perf[2]), 2),
            **metrics,
        }
    except ImportError:
        logger.info("PyPortfolioOpt 未安装，跳过有效前沿优化")
        return None
    except Exception as e:
        logger.warning("PyPortfolioOpt 优化失败: %s", e)
        return None


# ─── 等权重降级 ───────────────────────────────────────────────────────────────

def _equal_weight(prices: pd.DataFrame) -> dict:
    syms = list(prices.columns)
    w = round(1.0 / len(syms), 4)
    weights = {s: w for s in syms}
    metrics = _compute_portfolio_metrics(weights, prices)
    return {"weights": weights, "method": "等权重（优化器不可用）", **metrics}


# ─── 主入口 ───────────────────────────────────────────────────────────────────

def build_portfolio_strategy(
    target_return: Optional[float],
    max_drawdown: Optional[float],
    period: str = "3y",
) -> Optional[dict]:
    """
    目标驱动组合优化主入口。

    Args:
        target_return: 目标年化收益（小数，如 0.50 = 50%）
        max_drawdown:  最大可接受回撤（小数，如 0.10 = 10%）
        period:        历史数据回溯周期

    Returns:
        策略 dict，可直接插入策略猎手结果列表，包含：
        - weights: {"SPY": 0.40, "QQQ": 0.30, ...}
        - annual_return_pct / max_drawdown_pct: 历史回测估算值
        - method: 使用的优化方法
        - name/description/source 等界面字段
        None 表示获取数据失败。
    """
    # None = 不设限，用保守默认值做优化计算
    target_return = target_return if target_return is not None else 0.15
    max_drawdown = max_drawdown if max_drawdown is not None else 0.20
    symbols = _select_symbols(target_return, max_drawdown)
    prices = _fetch_prices(symbols, period)
    if prices is None:
        return None

    # 优先链
    result = (
        _optimize_riskfolio(prices, target_return)
        or _optimize_pypfopt(prices, target_return)
        or _equal_weight(prices)
    )

    weights = result["weights"]
    top5 = sorted(weights.items(), key=lambda x: x[1], reverse=True)[:5]
    holdings_str = " + ".join(f"{s}({w*100:.0f}%)" for s, w in top5 if w > 0.01)

    est_ret = result.get("annual_return_pct")
    est_dd = result.get("max_drawdown_pct")

    result.update({
        "id": "portfolio_optimized",
        "name": f"目标优化组合（{holdings_str}）",
        "description": (
            f"基于目标（年化{target_return*100:.0f}%，回撤≤{max_drawdown*100:.0f}%），"
            f"使用 {result['method']} 构建多资产组合。持仓：{holdings_str}。"
            + (f" 历史回测：年化{est_ret}%，最大回撤{est_dd}%。" if est_ret else "")
        ),
        "source": result["method"],
        "instrument": "portfolio",
        "direction": "bullish",
        "style": "portfolio_optimization",
        "risk_level": "medium" if max_drawdown <= 0.15 else "high",
        "annual_return_range": [
            int(est_ret * 0.8) if est_ret else int(target_return * 80),
            int(est_ret * 1.2) if est_ret else int(target_return * 120),
        ],
        "win_rate_pct": None,
        "why_it_works": (
            "通过现代投资组合理论（MPT）和条件回撤风险（CDaR）约束，"
            "在你设定的回撤上限内寻找历史夏普比最优的资产权重组合。"
            "多资产分散降低单一资产风险，相关性低的品种组合可获得更优风险收益比。"
        ),
        "best_market": "多资产分散配置，适应各类市场环境",
        "default_symbols": list(weights.keys())[:3],
        "holdings_breakdown": [
            {"symbol": s, "weight_pct": round(w * 100, 1)}
            for s, w in sorted(weights.items(), key=lambda x: x[1], reverse=True)
            if w > 0.01
        ],
        "is_portfolio": True,
        # 优化参数（用于详情展示）
        "opt_params": {
            "目标年化收益": f"{target_return*100:.0f}%",
            "回撤上限": f"{max_drawdown*100:.0f}%",
            "数据回溯期": period,
            "优化引擎": result["method"],
            "历史年化": f"{est_ret}%" if est_ret else "—",
            "历史最大回撤": f"{est_dd}%" if est_dd else "—",
            "夏普比率": str(result.get("sharpe", "—")),
            "持仓数量": str(len([s for s, w in weights.items() if w > 0.01])),
        },
    })

    return result


# ─── PyPortfolioOpt 权重工具（供 combo_scorer 使用）──────────────────────────

def optimize_stock_weights(
    symbols: list[str],
    target_return: float = 0.15,
    period: str = "2y",
) -> dict[str, float]:
    """
    为给定股票列表优化持仓权重（供 combo_scorer 调用）。

    Returns:
        {"AAPL": 0.35, "MSFT": 0.25, ...} 或等权重（优化失败时）
    """
    prices = _fetch_prices(symbols, period)
    if prices is None:
        w = round(1.0 / len(symbols), 4)
        return {s: w for s in symbols}

    result = _optimize_pypfopt(prices, target_return) or _equal_weight(prices)
    return result["weights"]
