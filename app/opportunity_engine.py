"""
Goal-Driven Trading OS — Opportunity Engine
多策略推荐引擎：正股、Call、Put、Sell Put、Covered Call、组合策略

根据用户的收益和回撤目标，筛选所有可行的交易机会。
"""
import math
import numpy as np
import pandas as pd
from dataclasses import dataclass, field
from market_data import fetch_stock_history, compute_technicals, fetch_current_price
from stock_screener import diagnose_stock, StockDiagnosis, SECTORS


@dataclass
class Opportunity:
    """一个交易机会"""
    symbol: str
    strategy: str          # buy_stock / buy_call / buy_put / sell_put / covered_call / combo
    strategy_name: str     # 显示名称
    direction: str         # bullish / bearish / neutral
    score: int             # 0-100
    # 预期收益
    est_return_pct: float  # 预估收益率
    est_return_usd: float  # 预估收益金额
    max_loss_pct: float    # 最大亏损率
    max_loss_usd: float    # 最大亏损金额
    # 关键参数
    entry_price: float
    target_price: float
    stop_loss: float
    # 期权参数 (如适用)
    strike: float = 0
    expiry: str = ""
    delta: float = 0
    premium: float = 0
    contracts: int = 0
    # 仓位
    capital_required: float = 0
    shares_or_contracts: int = 0
    # 诊断
    diagnosis: StockDiagnosis = None
    reason: str = ""
    risk_level: str = ""   # low / medium / high
    # 关联策略
    triggered_by: str = ""   # 触发此机会的策略名称
    # 组合信息
    combo_parts: list = field(default_factory=list)


def find_opportunities(
    goals_return: float = 0.15,
    goals_drawdown: float = 0.10,
    risk_per_trade: float = 0.02,
    account_balance: float = 100000,
    sectors: list = None,
    max_results: int = 30,
    strategy_configs: list = None,   # 用户配置的活跃策略列表
) -> dict:
    """
    全市场多策略扫描

    对每个标的评估策略，筛选符合目标的机会，按评分排序。
    若传入 strategy_configs，则只评估用户启用的策略，并标注触发策略名称。
    """
    if sectors is None:
        sectors = ["TECH", "CHIP", "ETF"]

    all_symbols = set()
    for sec_key in sectors:
        sec = SECTORS.get(sec_key, {})
        all_symbols.update(sec.get("symbols", []))

    from concurrent.futures import ThreadPoolExecutor, as_completed

    opportunities = []

    def _process_symbol(symbol):
        diag = diagnose_stock(symbol)
        if diag.current_price <= 0:
            return []
        return _evaluate_all_strategies(diag, goals_return, goals_drawdown, risk_per_trade, account_balance)

    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {executor.submit(_process_symbol, sym): sym for sym in sorted(all_symbols)}
        for future in as_completed(futures):
            try:
                opps = future.result()
                opportunities.extend(opps)
            except Exception:
                continue

    # 按评分排序
    opportunities.sort(key=lambda x: x.score, reverse=True)

    # 如果传入了用户策略，过滤 + 打标签
    if strategy_configs:
        opportunities = _apply_strategy_configs(opportunities, strategy_configs)

    # 筛选符合目标的
    compatible = [o for o in opportunities if o.max_loss_pct <= goals_drawdown and o.est_return_pct > 0]
    incompatible = [o for o in opportunities if o not in compatible]

    # 如果兼容的不够，生成组合策略
    combos = []
    if len(compatible) >= 2:
        combos = _build_combos(compatible[:10], goals_return, goals_drawdown, account_balance)

    return {
        "opportunities": compatible[:max_results],
        "incompatible": incompatible[:10],
        "combos": combos[:5],
        "total_scanned": len(all_symbols),
        "total_strategies": len(opportunities),
        "total_compatible": len(compatible),
    }


def _apply_strategy_configs(opportunities: list, strategy_configs: list) -> list:
    """
    用用户配置的策略过滤机会列表，并打上触发策略标签。

    逻辑：
    - 只保留与至少一个启用策略 instrument 匹配的机会
    - 对每个机会，检查匹配策略的 params 是否满足（RSI阈值、安全边际等）
    - 设置 triggered_by 为触发该机会的策略名称
    """
    # instrument 映射（strategy 字段 -> StrategyConfig.instrument 字段名）
    INSTRUMENT_MAP = {
        "buy_stock": "stock",
        "buy_call": "call",
        "buy_put": "put",
        "sell_put": "sell_put",
        "covered_call": "covered_call",
    }

    result = []
    for opp in opportunities:
        opp_inst = INSTRUMENT_MAP.get(opp.strategy, opp.strategy)
        matched_names = []

        for sc in strategy_configs:
            if sc.get("instrument") != opp_inst:
                continue
            # 检查方向是否兼容
            sc_dir = sc.get("direction", "neutral")
            if sc_dir == "bullish" and opp.direction == "bearish":
                continue
            if sc_dir == "bearish" and opp.direction == "bullish":
                continue

            # 检查策略 params 中的额外条件
            params = sc.get("params", {})
            diag = opp.diagnosis

            # RSI 条件（策略设了阈值就检查）
            if diag and "rsi_threshold" in params:
                if diag.rsi > float(params["rsi_threshold"]):
                    continue

            # 安全边际条件（sell_put 专用）
            if opp_inst == "sell_put" and diag and "min_safety_margin" in params:
                if diag.safety_margin < float(params["min_safety_margin"]):
                    continue

            # VIX 范围（如果诊断有 VIX 信息的话，目前没有，跳过）

            matched_names.append(sc.get("display_name", sc.get("strategy_name", "")))

        if matched_names:
            opp.triggered_by = " · ".join(matched_names)
            result.append(opp)

    return result


def _evaluate_all_strategies(diag: StockDiagnosis, goals_return, goals_drawdown, risk_per_trade, account) -> list[Opportunity]:
    """对一个标的评估所有可行策略"""
    results = []
    price = diag.current_price
    atr = diag.atr_14 if diag.atr_14 > 0 else price * 0.02

    # 1. 买入正股 (Buy Stock)
    if diag.trend == "bullish" and diag.score >= 50:
        stop = price - atr * 2
        target = price + atr * 3
        risk_per_share = price - stop
        shares = _calc_shares(account, risk_per_trade, risk_per_share)
        if shares > 0:
            results.append(Opportunity(
                symbol=diag.symbol,
                strategy="buy_stock",
                strategy_name="买入正股",
                direction="bullish",
                score=diag.score,
                est_return_pct=round((target - price) / price, 4),
                est_return_usd=round((target - price) * shares, 2),
                max_loss_pct=round(risk_per_trade, 4),
                max_loss_usd=round(risk_per_share * shares, 2),
                entry_price=price,
                target_price=round(target, 2),
                stop_loss=round(stop, 2),
                capital_required=round(price * shares, 2),
                shares_or_contracts=shares,
                diagnosis=diag,
                reason=f"趋势向上 (MA200上方)，ATR止损 ${stop:.0f}，目标 ${target:.0f}",
                risk_level="medium",
            ))

    # 2. 买入 Call (Buy Call / LEAPS)
    if diag.trend == "bullish" and diag.score >= 55:
        # 估算 ATM Call 权利金 (简化：约 ATR * 2)
        premium_est = atr * 2
        strike = round(price / 5) * 5  # ATM rounded to $5
        contracts = max(1, int(account * risk_per_trade / (premium_est * 100)))
        target_pct = 0.50  # 目标 50% 收益
        results.append(Opportunity(
            symbol=diag.symbol,
            strategy="buy_call",
            strategy_name="买入 Call",
            direction="bullish",
            score=diag.score - 5,  # slightly lower than stock (higher risk)
            est_return_pct=round(target_pct, 4),
            est_return_usd=round(premium_est * 100 * contracts * target_pct, 2),
            max_loss_pct=round(premium_est * 100 * contracts / account, 4),
            max_loss_usd=round(premium_est * 100 * contracts, 2),
            entry_price=round(premium_est, 2),
            target_price=round(premium_est * 1.5, 2),
            stop_loss=0,
            strike=strike,
            expiry="30-60 DTE",
            delta=0.50,
            premium=round(premium_est, 2),
            contracts=contracts,
            capital_required=round(premium_est * 100 * contracts, 2),
            shares_or_contracts=contracts,
            diagnosis=diag,
            reason=f"趋势看涨，ATM Call ${strike}，权利金约 ${premium_est:.1f}，最多亏权利金",
            risk_level="high",
        ))

    # 3. 买入 Put (Buy Put) — 做空或对冲
    if diag.trend == "bearish" and diag.score <= 40:
        premium_est = atr * 1.5
        strike = round(price / 5) * 5
        contracts = max(1, int(account * risk_per_trade / (premium_est * 100)))
        results.append(Opportunity(
            symbol=diag.symbol,
            strategy="buy_put",
            strategy_name="买入 Put",
            direction="bearish",
            score=max(0, 50 - diag.score + 30),
            est_return_pct=0.40,
            est_return_usd=round(premium_est * 100 * contracts * 0.4, 2),
            max_loss_pct=round(premium_est * 100 * contracts / account, 4),
            max_loss_usd=round(premium_est * 100 * contracts, 2),
            entry_price=round(premium_est, 2),
            target_price=round(premium_est * 1.4, 2),
            stop_loss=0,
            strike=strike,
            expiry="30-45 DTE",
            delta=-0.45,
            premium=round(premium_est, 2),
            contracts=contracts,
            capital_required=round(premium_est * 100 * contracts, 2),
            shares_or_contracts=contracts,
            diagnosis=diag,
            reason=f"趋势下行，ATM Put ${strike}，用于做空或对冲多头持仓",
            risk_level="high",
        ))

    # 4. Sell Put — 核心策略
    if diag.safety_margin > 0.05 and diag.score >= 40:
        strike = diag.suggested_strike
        premium_est = atr * 0.3  # 简化估算
        contracts = max(1, int(account * 0.15 / (strike * 100)))  # 最多用 15% 资金
        max_loss = (strike - (strike * 0.85)) * 100 * contracts  # 假设最大跌 15%
        results.append(Opportunity(
            symbol=diag.symbol,
            strategy="sell_put",
            strategy_name="Sell Put",
            direction="neutral",
            score=diag.score + 5,  # Sell Put bonus if high safety margin
            est_return_pct=round(premium_est * 100 * contracts / (strike * 100 * contracts), 4),
            est_return_usd=round(premium_est * 100 * contracts, 2),
            max_loss_pct=round(max_loss / account, 4),
            max_loss_usd=round(max_loss, 2),
            entry_price=round(premium_est, 2),
            target_price=0,
            stop_loss=round(strike * 0.85, 2),
            strike=strike,
            expiry=f"{diag.suggested_dte} DTE",
            delta=-0.20,
            premium=round(premium_est, 2),
            contracts=contracts,
            capital_required=round(strike * 100 * contracts, 2),
            shares_or_contracts=contracts,
            diagnosis=diag,
            reason=f"支撑位 ${diag.support_level:.0f}，安全边际 {diag.safety_margin*100:.1f}%，收权利金",
            risk_level="low" if diag.safety_margin > 0.10 else "medium",
        ))

    # 5. Covered Call — 持有正股 + 卖 Call
    if diag.trend in ("bullish", "neutral") and diag.score >= 45:
        call_strike = round((price * 1.05) / 5) * 5  # 5% OTM
        call_premium = atr * 0.4
        shares = max(100, _calc_shares(account, 0.10, price) // 100 * 100)  # 至少 100 股
        if shares >= 100:
            contracts_cc = shares // 100
            total_cost = price * shares
            total_premium = call_premium * 100 * contracts_cc
            results.append(Opportunity(
                symbol=diag.symbol,
                strategy="covered_call",
                strategy_name="Covered Call",
                direction="neutral",
                score=diag.score,
                est_return_pct=round((call_premium * 100 * contracts_cc + (call_strike - price) * shares) / total_cost, 4),
                est_return_usd=round(total_premium + (call_strike - price) * shares, 2),
                max_loss_pct=round((price - diag.support_level) * shares / account, 4),
                max_loss_usd=round((price - diag.support_level) * shares, 2),
                entry_price=price,
                target_price=call_strike,
                stop_loss=round(diag.support_level, 2),
                strike=call_strike,
                expiry="30-45 DTE",
                delta=0.70,
                premium=round(call_premium, 2),
                contracts=contracts_cc,
                capital_required=round(total_cost, 2),
                shares_or_contracts=shares,
                diagnosis=diag,
                reason=f"持有 {shares} 股 + 卖 {contracts_cc} 张 Call ${call_strike}，收权利金 ${total_premium:.0f}",
                risk_level="medium",
            ))

    return results


def _build_combos(opportunities: list[Opportunity], goals_return, goals_drawdown, account) -> list[dict]:
    """
    组合策略：挑选 2-4 个低相关的机会组成组合，
    使得组合收益 >= 目标，组合风险 <= 目标回撤
    """
    # 按不同策略类型分组，每组取最优
    by_strategy = {}
    for opp in opportunities:
        key = f"{opp.strategy}_{opp.symbol}"
        if key not in by_strategy or opp.score > by_strategy[key].score:
            by_strategy[key] = opp

    candidates = list(by_strategy.values())
    if len(candidates) < 2:
        return []

    combos = []

    # 组合 1: 稳健组合 (Sell Put × 2-3)
    sell_puts = sorted([o for o in candidates if o.strategy == "sell_put"], key=lambda x: x.score, reverse=True)
    if len(sell_puts) >= 2:
        combo_items = sell_puts[:3]
        combos.append(_score_combo("稳健收租组合", "多标的 Sell Put 分散风险", combo_items, account, goals_return, goals_drawdown))

    # 组合 2: 进攻组合 (Buy Stock + Buy Call)
    stocks = [o for o in candidates if o.strategy == "buy_stock"][:2]
    calls = [o for o in candidates if o.strategy == "buy_call"][:1]
    if stocks and calls:
        combos.append(_score_combo("进攻组合", "正股 + Call 看涨组合", stocks + calls, account, goals_return, goals_drawdown))

    # 组合 3: 攻守兼备 (Buy Stock + Sell Put + Covered Call)
    covered = [o for o in candidates if o.strategy == "covered_call"][:1]
    if stocks and sell_puts:
        mix = stocks[:1] + sell_puts[:1]
        if covered:
            mix += covered[:1]
        combos.append(_score_combo("攻守兼备组合", "正股 + Sell Put + Covered Call 平衡风险收益", mix, account, goals_return, goals_drawdown))

    # 组合 4: 纯对冲 (Sell Put + Buy Put on different underlyings)
    puts = [o for o in candidates if o.strategy == "buy_put"][:1]
    if sell_puts and puts:
        combos.append(_score_combo("对冲组合", "Sell Put 收租 + Buy Put 保护", sell_puts[:2] + puts, account, goals_return, goals_drawdown))

    combos.sort(key=lambda x: x["score"], reverse=True)
    return combos


def _score_combo(name, desc, items, account, goals_return, goals_drawdown) -> dict:
    total_return = sum(o.est_return_usd for o in items)
    total_capital = sum(o.capital_required for o in items)
    total_risk = sum(o.max_loss_usd for o in items)
    combo_return_pct = total_return / account if account > 0 else 0
    combo_risk_pct = total_risk / account if account > 0 else 0

    # 假设持仓间 50% 相关性，风险不是简单相加
    diversified_risk = combo_risk_pct * 0.7  # 分散后风险降低 30%

    meets_return = combo_return_pct >= goals_return * 0.5  # 至少达到目标的一半
    meets_risk = diversified_risk <= goals_drawdown

    score = 50
    if meets_return:
        score += 20
    if meets_risk:
        score += 20
    if len(set(o.symbol for o in items)) >= 2:
        score += 10  # 分散加分

    return {
        "name": name,
        "description": desc,
        "parts": items,
        "total_return_usd": round(total_return, 2),
        "total_return_pct": round(combo_return_pct * 100, 2),
        "total_capital": round(total_capital, 2),
        "total_risk_usd": round(total_risk, 2),
        "total_risk_pct": round(diversified_risk * 100, 2),
        "meets_return": meets_return,
        "meets_risk": meets_risk,
        "compatible": meets_return and meets_risk,
        "score": min(100, score),
        "count": len(items),
        "symbols": list(set(o.symbol for o in items)),
    }


def _calc_shares(account, risk_pct, risk_per_share) -> int:
    if risk_per_share <= 0:
        return 0
    return max(0, math.floor(account * risk_pct / risk_per_share))
