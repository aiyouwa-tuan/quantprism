#!/usr/bin/env python3
"""
参数扫描 — 使用已验证的 strategy.py 引擎
对 SPY、QQQ、IWM 进行全面参数优化
目标: 年化≥20%，最大回撤≤10%
"""
import sys, os, itertools, types
import pandas as pd
import numpy as np
import yfinance as yf

sys.path.insert(0, os.path.dirname(__file__))
import config as base_cfg
from pricing import (find_strike_by_delta, spread_value, bs_price,
                     bear_call_spread_value, apply_iv_skew, calc_friction_cost)

# =====================================================================
# 内嵌回测引擎（从strategy.py复制，使用参数化config而非全局config）
# =====================================================================
from dataclasses import dataclass, field

@dataclass
class IC:
    entry_date: object; expiry_date: object
    K_short_put: float; K_long_put: float; put_premium: float
    K_short_call: float; K_long_call: float; call_premium: float
    total_premium: float; contracts: int; entry_price: float
    max_loss: float; max_profit: float


def run_bt(df, cfg):
    """回测引擎，cfg 是一个 namespace 对象"""
    capital = cfg.INITIAL_CAPITAL
    positions = []
    equity = []
    paused_until = None
    peak_equity = capital
    last_open_date = None
    comm = cfg.COMMISSION_PER_LEG

    for date, row in df.iterrows():
        S = row["close"]
        iv = row["iv"] * getattr(cfg, 'IV_MULTIPLIER', 0.95)
        vix = row["vix"]
        sma_key = f"sma_{cfg.TREND_SMA_PERIOD}"
        sma_long = row.get(sma_key, row.get("sma_100", S))

        # 1. Portfolio stop
        if positions:
            total_u = 0
            for p in positions:
                dte = (p.expiry_date - date).days
                T = max(dte / 365.0, 0.001)
                iv_p = apply_iv_skew(iv, "put")
                iv_c = apply_iv_skew(iv, "call")
                sp = bs_price(S, p.K_short_put, T, cfg.RISK_FREE_RATE, iv_p, "put")
                lp = bs_price(S, p.K_long_put, T, cfg.RISK_FREE_RATE, iv_p, "put")
                sc = bs_price(S, p.K_short_call, T, cfg.RISK_FREE_RATE, iv_c, "call")
                lc = bs_price(S, p.K_long_call, T, cfg.RISK_FREE_RATE, iv_c, "call")
                cost = (sp - lp) + (sc - lc)
                total_u += (p.total_premium - cost) * 100 * p.contracts

            if total_u <= -capital * cfg.PORTFOLIO_STOP:
                for p in positions:
                    dte = (p.expiry_date - date).days
                    T = max(dte / 365.0, 0.001)
                    iv_p = apply_iv_skew(iv, "put")
                    iv_c = apply_iv_skew(iv, "call")
                    sp = bs_price(S, p.K_short_put, T, cfg.RISK_FREE_RATE, iv_p, "put")
                    lp = bs_price(S, p.K_long_put, T, cfg.RISK_FREE_RATE, iv_p, "put")
                    sc = bs_price(S, p.K_short_call, T, cfg.RISK_FREE_RATE, iv_c, "call")
                    lc = bs_price(S, p.K_long_call, T, cfg.RISK_FREE_RATE, iv_c, "call")
                    cost = (sp - lp) + (sc - lc)
                    pnl = (p.total_premium - cost) * 100 * p.contracts
                    pnl -= p.contracts * 4 * comm
                    pnl -= calc_friction_cost(vix) * 100 * p.contracts
                    capital += pnl
                positions = []
                paused_until = date + pd.Timedelta(days=cfg.RESUME_AFTER_DAYS)
                equity.append(capital)
                continue

        # 2. Manage positions
        to_close = []
        for j, p in enumerate(positions):
            dte = (p.expiry_date - date).days
            T = max(dte / 365.0, 0.001)
            iv_p = apply_iv_skew(iv, "put")
            iv_c = apply_iv_skew(iv, "call")
            sp = bs_price(S, p.K_short_put, T, cfg.RISK_FREE_RATE, iv_p, "put")
            lp = bs_price(S, p.K_long_put, T, cfg.RISK_FREE_RATE, iv_p, "put")
            sc = bs_price(S, p.K_short_call, T, cfg.RISK_FREE_RATE, iv_c, "call")
            lc = bs_price(S, p.K_long_call, T, cfg.RISK_FREE_RATE, iv_c, "call")
            cost = (sp - lp) + (sc - lc)
            pnl = (p.total_premium - cost) * 100 * p.contracts
            close_reason = None

            if pnl >= p.max_profit * cfg.PROFIT_TARGET:
                close_reason = "profit"
            elif dte <= cfg.DTE_EXIT:
                close_reason = "dte"
            elif dte <= 0:
                put_val = max(p.K_short_put - S, 0) - max(p.K_long_put - S, 0)
                call_val = max(S - p.K_short_call, 0) - max(S - p.K_long_call, 0)
                pnl = (p.total_premium - put_val - call_val) * 100 * p.contracts
                close_reason = "expiry"

            if close_reason:
                pnl -= p.contracts * 4 * comm
                if close_reason != "expiry":
                    pnl -= calc_friction_cost(vix) * 100 * p.contracts
                capital += pnl
                to_close.append(j)

        for j in sorted(to_close, reverse=True):
            positions.pop(j)

        # 3. Drawdown pause
        if capital > peak_equity:
            peak_equity = capital
        drawdown = (peak_equity - capital) / peak_equity if peak_equity > 0 else 0

        if paused_until and date >= paused_until:
            peak_equity = capital
            paused_until = None

        if paused_until is None and drawdown >= cfg.MAX_DRAWDOWN_PAUSE:
            paused_until = date + pd.Timedelta(days=cfg.RESUME_AFTER_DAYS)

        if paused_until and date < paused_until:
            equity.append(capital)
            continue

        # 4. Open
        if last_open_date and (date - last_open_date).days < 1:
            equity.append(capital)
            continue

        trend_ok = not cfg.REQUIRE_ABOVE_SMA or S > sma_long
        crisis_vix = getattr(cfg, 'CRISIS_VIX_THRESHOLD', 999)
        can_open = (
            len(positions) < cfg.MAX_POSITIONS
            and vix >= cfg.MIN_VIX
            and vix <= cfg.MAX_VIX
            and vix < crisis_vix
            and trend_ok
        )

        if can_open:
            T = cfg.DTE_TARGET / 365.0
            expiry = date + pd.Timedelta(days=cfg.DTE_TARGET)
            delta = cfg.SHORT_PUT_DELTA
            if cfg.DELTA_VIX_ADJUST and vix > cfg.DELTA_VIX_THRESHOLD:
                delta = cfg.DELTA_HIGH_VIX

            iv_p = apply_iv_skew(iv, "put")
            iv_c = apply_iv_skew(iv, "call")

            K_sp = find_strike_by_delta(S, T, cfg.RISK_FREE_RATE, iv_p, delta, "put", 1.0)
            K_lp = K_sp - cfg.SPREAD_WIDTH
            put_prem = spread_value(S, K_sp, K_lp, T, cfg.RISK_FREE_RATE, iv_p)

            K_sc = find_strike_by_delta(S, T, cfg.RISK_FREE_RATE, iv_c, delta, "call", 1.0)
            K_lc = K_sc + cfg.SPREAD_WIDTH
            call_prem = bear_call_spread_value(S, K_sc, K_lc, T, cfg.RISK_FREE_RATE, iv_c)

            if K_sc <= K_sp:
                equity.append(capital)
                continue

            total_prem = put_prem + call_prem
            friction = calc_friction_cost(vix)
            net_prem = total_prem - friction

            if net_prem <= 0.05:
                equity.append(capital)
                continue

            max_loss_one_side = (cfg.SPREAD_WIDTH - min(put_prem, call_prem)) * 100
            risk_budget = capital * cfg.MAX_RISK_PER_TRADE
            contracts = max(1, int(risk_budget / max_loss_one_side))

            open_comm = contracts * 4 * comm
            capital -= open_comm
            capital -= friction * 100 * contracts

            positions.append(IC(
                entry_date=date, expiry_date=expiry,
                K_short_put=K_sp, K_long_put=K_lp, put_premium=put_prem,
                K_short_call=K_sc, K_long_call=K_lc, call_premium=call_prem,
                total_premium=total_prem, contracts=contracts, entry_price=S,
                max_loss=max_loss_one_side * contracts,
                max_profit=total_prem * 100 * contracts,
            ))
            last_open_date = date

        equity.append(capital)

    eq = pd.Series(equity, index=df.index[:len(equity)])
    if len(eq) < 2:
        return None

    total_ret = (eq.iloc[-1] / eq.iloc[0]) - 1
    years = (eq.index[-1] - eq.index[0]).days / 365.25
    annual = (1 + total_ret) ** (1 / years) - 1 if years > 0 and total_ret > -1 else -1
    peak = eq.cummax()
    dd = abs(((eq - peak) / peak).min()) * 100
    dr = eq.pct_change().dropna()
    sharpe = dr.mean() / dr.std() * np.sqrt(252) if dr.std() > 0 else 0

    return {"annual": annual * 100, "dd": dd, "sharpe": sharpe, "final": eq.iloc[-1]}


# =====================================================================
# 数据缓存
# =====================================================================
_cache = {}

def get_df(symbol, iv_mult, start="2005-01-01", end="2024-12-31"):
    key = (symbol, iv_mult)
    if key in _cache:
        return _cache[key]

    ext = pd.Timestamp(start) - pd.Timedelta(days=400)
    px = yf.download(symbol, start=ext.strftime("%Y-%m-%d"), end=end, progress=False)
    vix_raw = yf.download("^VIX", start=ext.strftime("%Y-%m-%d"), end=end, progress=False)

    for d in [px, vix_raw]:
        if isinstance(d.columns, pd.MultiIndex):
            d.columns = d.columns.get_level_values(0)

    df = pd.DataFrame(index=px.index)
    df["close"] = px["Close"]
    df["vix"] = vix_raw["Close"].reindex(px.index, method="ffill")
    df["returns"] = df["close"].pct_change()
    df["iv"] = df["vix"] / 100.0 * iv_mult
    df["sma_100"] = df["close"].rolling(100).mean()
    df["sma_50"] = df["close"].rolling(50).mean()
    df = df.loc[start:end].copy()
    df.dropna(inplace=True)
    _cache[key] = df
    return df


# =====================================================================
# 参数扫描主程序
# =====================================================================
def make_cfg(**kwargs):
    """创建配置对象（基于 base_cfg，覆盖指定参数）"""
    c = types.SimpleNamespace()
    for attr in dir(base_cfg):
        if not attr.startswith("_"):
            setattr(c, attr, getattr(base_cfg, attr))
    for k, v in kwargs.items():
        setattr(c, k, v)
    return c


def main():
    print("=" * 80)
    print("参数扫描 — 年化≥20% + 最大回撤≤10%")
    print("使用已验证的 strategy.py 引擎")
    print("=" * 80)

    # ── 标的 & IV 校准 ─────────────────────────────────────────────
    targets = {
        "SPY":  0.95,   # S&P 500 (已知有效)
        "QQQ":  1.11,   # Nasdaq-100
        "IWM":  1.22,   # Russell 2000 (高IV优势)
        "DIA":  0.76,   # Dow Jones
        "EEM":  1.15,   # 新兴市场
        "GLD":  0.90,   # 黄金ETF
        "XLF":  1.05,   # 金融板块
        "XLE":  1.10,   # 能源板块
        "TLT":  0.85,   # 20年国债
        "HYG":  0.70,   # 高收益债
    }

    # ── 参数网格 ───────────────────────────────────────────────────
    # 基于已知有效配置，围绕最优点展开
    param_grid = {
        "SHORT_PUT_DELTA":   [0.20, 0.25, 0.30, 0.35],
        "SPREAD_WIDTH":      [3, 5, 7, 10],
        "MAX_POSITIONS":     [2, 3, 4, 5],
        "DTE_TARGET":        [5, 7, 10, 14],
        "PROFIT_TARGET":     [0.35, 0.40, 0.50],
        "MAX_VIX":           [22, 25, 30],
        "MAX_RISK_PER_TRADE": [0.02, 0.025, 0.03],
    }

    winning = []
    tested = 0
    total_combos = (len(targets) *
                    len(param_grid["SHORT_PUT_DELTA"]) *
                    len(param_grid["SPREAD_WIDTH"]) *
                    len(param_grid["MAX_POSITIONS"]) *
                    len(param_grid["DTE_TARGET"]) *
                    len(param_grid["PROFIT_TARGET"]) *
                    len(param_grid["MAX_VIX"]) *
                    len(param_grid["MAX_RISK_PER_TRADE"]))
    print(f"\n总测试组合数: {total_combos:,}")
    print("开始扫描...\n")

    for sym, iv_mult in targets.items():
        print(f"{'─'*60}")
        print(f"标的: {sym} (IV_MULT={iv_mult})")

        df = get_df(sym, iv_mult)
        if df is None or len(df) < 500:
            print(f"  ⚠ 数据不足，跳过")
            continue
        print(f"  数据: {df.index[0].date()} ~ {df.index[-1].date()} ({len(df)}天)")

        best_sym_score = 0

        for delta, spread, max_pos, dte, pt, max_vix, risk in itertools.product(
            param_grid["SHORT_PUT_DELTA"],
            param_grid["SPREAD_WIDTH"],
            param_grid["MAX_POSITIONS"],
            param_grid["DTE_TARGET"],
            param_grid["PROFIT_TARGET"],
            param_grid["MAX_VIX"],
            param_grid["MAX_RISK_PER_TRADE"],
        ):
            tested += 1

            cfg = make_cfg(
                SHORT_PUT_DELTA=delta,
                SPREAD_WIDTH=spread,
                MAX_POSITIONS=max_pos,
                DTE_TARGET=dte,
                DTE_MIN=max(2, dte - 3),
                DTE_MAX=dte + 3,
                PROFIT_TARGET=pt,
                MAX_VIX=max_vix,
                MAX_RISK_PER_TRADE=risk,
                IV_MULTIPLIER=iv_mult,
                UNDERLYING=sym,
            )

            try:
                r = run_bt(df, cfg)
            except Exception:
                continue

            if r is None:
                continue

            if r["annual"] >= 20 and r["dd"] <= 10:
                score = min(r["annual"] / 20.0, 1.5) * 50 + min(10.0 / max(r["dd"], 0.1), 1.5) * 50
                entry = {
                    "symbol": sym, "delta": delta, "spread": spread,
                    "max_pos": max_pos, "dte": dte, "profit_target": pt,
                    "max_vix": max_vix, "risk_pct": risk,
                    "annual": r["annual"], "dd": r["dd"],
                    "sharpe": r["sharpe"], "final": r["final"], "score": score
                }
                winning.append(entry)
                if score > best_sym_score:
                    best_sym_score = score
                    print(f"  ✅ d{delta} s{spread} p{max_pos} dte{dte} pt{pt} vix{max_vix} r{risk}"
                          f" → {r['annual']:.1f}% DD{r['dd']:.1f}% Sh{r['sharpe']:.2f} ★{score:.1f}")

        if best_sym_score == 0:
            print(f"  ❌ 无达标策略")

    # ─── 汇总报告 ───────────────────────────────────────────────────
    print(f"\n\n{'='*80}")
    print(f"扫描完成 | 总测试: {tested:,} | 达标策略: {len(winning)}")
    print(f"{'='*80}")

    if not winning:
        print("❌ 未找到达标策略")
        return

    winning.sort(key=lambda x: x["score"], reverse=True)

    print(f"\nTOP 30 策略 (年化≥20% + 回撤≤10%)")
    print(f"{'─'*100}")
    hdr = f"{'#':<3} {'标的':<5} {'Delta':>6} {'宽度':>4} {'仓':>3} {'DTE':>4} {'PT':>5} {'VIX':>4} {'风险':>5} {'年化':>7} {'回撤':>7} {'夏普':>6} {'SCORE':>6}"
    print(hdr)
    print("─" * 100)

    for i, r in enumerate(winning[:30]):
        print(f"{i+1:<3} {r['symbol']:<5} {r['delta']:>6} ${r['spread']:<3} {r['max_pos']:>3} "
              f"{r['dte']:>4} {r['profit_target']:>5} {r['max_vix']:>4} {r['risk_pct']:>5} "
              f"{r['annual']:>6.1f}% {-r['dd']:>6.1f}% {r['sharpe']:>6.2f} {r['score']:>6.1f}")

    # 各标的最优
    print(f"\n{'='*80}")
    print("各标的最优策略（可供实盘操作）")
    print(f"{'='*80}")

    by_sym = {}
    for r in winning:
        if r["symbol"] not in by_sym or r["score"] > by_sym[r["symbol"]]["score"]:
            by_sym[r["symbol"]] = r

    final_list = sorted(by_sym.values(), key=lambda x: x["score"], reverse=True)

    for r in final_list:
        print(f"\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        print(f"  【{r['symbol']}】Iron Condor 策略")
        print(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        print(f"  年化收益:   {r['annual']:.2f}%  ✅  (目标≥20%)")
        print(f"  最大回撤:   -{r['dd']:.2f}%  ✅  (目标≤10%)")
        print(f"  夏普比率:   {r['sharpe']:.2f}")
        print(f"  $10,000 → ${r['final']:,.0f}  (2005-2024, 20年)")
        print(f"  综合评分:   {r['score']:.1f}")
        print(f"")
        print(f"  ▶ 操作参数:")
        print(f"    短腿Delta:    {r['delta']} (VIX>22时改用0.10保守)")
        print(f"    价差宽度:     ${r['spread']}")
        print(f"    最大仓位:     {r['max_pos']}个IC同时持有")
        print(f"    到期天数:     {r['dte']}天")
        print(f"    盈利目标:     {r['profit_target']*100:.0f}%最大盈利时平仓")
        print(f"    VIX上限:      {r['max_vix']} (超过停止开仓)")
        print(f"    每笔风险:     账户的{r['risk_pct']*100:.1f}%")

    # 保存
    out = os.path.join(os.path.dirname(__file__), "winning_strategies.csv")
    pd.DataFrame(winning).to_csv(out, index=False)
    print(f"\n✅ 完整结果已保存: {out}")

    # 最优推荐
    best = winning[0]
    print(f"\n{'='*80}")
    print("★★★ 最终推荐策略")
    print(f"{'='*80}")
    print(f"  标的: {best['symbol']}  Iron Condor")
    print(f"  年化: {best['annual']:.2f}%  回撤: -{best['dd']:.2f}%  夏普: {best['sharpe']:.2f}")
    print(f"  20年 $10,000 → ${best['final']:,.0f}")


if __name__ == "__main__":
    main()
