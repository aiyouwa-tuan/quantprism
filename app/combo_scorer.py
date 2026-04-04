"""
QuantPrism — Smart Combo Recommendation Engine
Score scan matches and recommend optimal portfolios
"""
import numpy as np


def score_match(match: dict) -> float:
    """
    Score a single scan match 0-100 based on multiple factors.
    """
    score = 0.0

    # Risk/Reward ratio (30% weight, max at 3:1)
    rr = match.get("risk_reward", 0)
    score += min(rr / 3.0, 1.0) * 30

    # Signal strength / confidence (20% weight)
    confidence = match.get("confidence", 0.5)
    score += confidence * 20

    # Price vs support distance (15% weight — closer to support = better)
    stop_pct = abs(match.get("stop_loss_pct", 5))
    if stop_pct < 3:
        score += 15
    elif stop_pct < 5:
        score += 10
    elif stop_pct < 8:
        score += 5

    # Target upside (20% weight)
    target_pct = match.get("target_pct", 0)
    score += min(target_pct / 20.0, 1.0) * 20

    # Volume / liquidity (15% weight) — prefer higher volume
    volume = match.get("volume", 0)
    if volume > 5_000_000:
        score += 15
    elif volume > 1_000_000:
        score += 10
    elif volume > 500_000:
        score += 5

    return round(min(score, 100), 1)


def recommend_combos(matches: list, account_balance: float = 100000) -> list:
    """
    Generate 3 portfolio combos from scored scan results:
    - Conservative (稳健): low risk, moderate return
    - Aggressive (进攻): high return, higher risk
    - Balanced (均衡): middle ground

    Returns:
        list of combo dicts, each with: name, icon, type, tickers, total_capital,
        expected_return_range, risk_level
    """
    if not matches:
        return []

    # Score all matches
    scored = []
    for m in matches:
        s = score_match(m)
        scored.append({**m, "ai_score": s})

    scored.sort(key=lambda x: x["ai_score"], reverse=True)

    # Sector diversification: max 2 per sector (if sector info available)
    def pick_diversified(pool, max_picks, prefer_low_risk=False):
        picked = []
        sector_count = {}
        if prefer_low_risk:
            pool = sorted(pool, key=lambda x: abs(x.get("stop_loss_pct", 5)))
        for m in pool:
            sector = m.get("sector", "Unknown")
            if sector_count.get(sector, 0) >= 2:
                continue
            picked.append(m)
            sector_count[sector] = sector_count.get(sector, 0) + 1
            if len(picked) >= max_picks:
                break
        return picked

    combos = []

    # 1. Conservative: top scored with lowest stop_loss_pct
    conservative_pool = [m for m in scored if abs(m.get("stop_loss_pct", 5)) < 5 and m["ai_score"] >= 50]
    if len(conservative_pool) < 2:
        conservative_pool = scored[:6]
    conservative_picks = pick_diversified(conservative_pool, 3, prefer_low_risk=True)
    if conservative_picks:
        cap = account_balance * 0.4
        syms = [p["symbol"] for p in conservative_picks]
        weights = optimize_combo_weights(syms, cap, target_return=0.12)
        combos.append({
            "name": "稳健组合",
            "icon": "shield",
            "type": "conservative",
            "border_color": "border-green-500/30",
            "hover_color": "border-green-500/50",
            "tickers": _format_tickers(conservative_picks, cap, weights),
            "total_capital": round(cap),
            "expected_return": "8-15%",
            "risk_level": "低",
            "count": len(conservative_picks),
            "optimizer": "PyPortfolioOpt",
        })

    # 2. Aggressive: highest potential return
    aggressive_pool = sorted(scored, key=lambda x: x.get("target_pct", 0), reverse=True)
    aggressive_picks = pick_diversified(aggressive_pool[:8], 4)
    if aggressive_picks:
        cap = account_balance * 0.6
        syms = [p["symbol"] for p in aggressive_picks]
        weights = optimize_combo_weights(syms, cap, target_return=0.30)
        combos.append({
            "name": "进攻组合",
            "icon": "zap",
            "type": "aggressive",
            "border_color": "border-red-500/30",
            "hover_color": "border-red-500/50",
            "tickers": _format_tickers(aggressive_picks, cap, weights),
            "total_capital": round(cap),
            "expected_return": "20-35%",
            "risk_level": "高",
            "count": len(aggressive_picks),
            "optimizer": "PyPortfolioOpt",
        })

    # 3. Balanced: mix of high score and moderate risk
    balanced_pool = [m for m in scored if m["ai_score"] >= 40]
    if len(balanced_pool) < 3:
        balanced_pool = scored
    balanced_picks = pick_diversified(balanced_pool, 3)
    if balanced_picks:
        cap = account_balance * 0.5
        syms = [p["symbol"] for p in balanced_picks]
        weights = optimize_combo_weights(syms, cap, target_return=0.18)
        combos.append({
            "name": "均衡组合",
            "icon": "scale",
            "type": "balanced",
            "border_color": "border-blue-500/30",
            "hover_color": "border-blue-500/50",
            "tickers": _format_tickers(balanced_picks, cap, weights),
            "total_capital": round(cap),
            "expected_return": "12-22%",
            "risk_level": "中",
            "count": len(balanced_picks),
            "optimizer": "PyPortfolioOpt",
        })

    return combos


def _format_tickers(picks, total_capital, weights: dict = None):
    """
    Format picks into mini-card data.
    若传入 weights（来自 PyPortfolioOpt），用优化权重分配资金；
    否则等权分配。
    """
    n = len(picks) or 1
    result = []
    for p in picks:
        sym = p.get("symbol", "???")
        if weights and sym in weights:
            alloc = round(total_capital * weights[sym])
        else:
            alloc = round(total_capital / n)
        result.append({
            "symbol": sym,
            "ai_score": p.get("ai_score", 0),
            "price": p.get("price", 0),
            "change_pct": p.get("change_pct", 0),
            "allocation": alloc,
            "weight_pct": round((weights[sym] * 100) if weights and sym in weights else (100 / n), 1),
        })
    return result


def optimize_combo_weights(
    symbols: list[str],
    total_capital: float,
    target_return: float = 0.15,
) -> dict[str, float]:
    """
    用 PyPortfolioOpt 为给定股票列表计算最优持仓权重。
    供 recommend_combos 调用，替代等权重分配。

    Returns:
        {"AAPL": 0.35, "MSFT": 0.25, ...}（权重加总为 1）
    """
    try:
        from portfolio_optimizer import optimize_stock_weights
        return optimize_stock_weights(symbols, target_return=target_return)
    except Exception:
        w = round(1.0 / max(len(symbols), 1), 4)
        return {s: w for s in symbols}
