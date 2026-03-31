#!/usr/bin/env python3
"""
快速策略扫描 — 仅对 SPY/QQQ/IWM/DIA 核心ETF
聚焦已知有效参数区间，快速找出全部达标策略
目标: 年化≥20%，最大回撤≤10%
"""
import sys, os, types
import pandas as pd
import numpy as np
import yfinance as yf

sys.path.insert(0, os.path.dirname(__file__))
import config as base_cfg
from pricing import (find_strike_by_delta, spread_value, bs_price,
                     bear_call_spread_value, apply_iv_skew, calc_friction_cost)
from dataclasses import dataclass

# =====================================================================
# 回测引擎（使用 apply_iv_skew 全局偏斜参数，与主 config 一致）
# =====================================================================
@dataclass
class IC:
    entry_date: object; expiry_date: object
    K_sp: float; K_lp: float; K_sc: float; K_lc: float
    put_prem: float; call_prem: float; total_prem: float
    contracts: int; entry_price: float; max_loss: float; max_profit: float


def run_bt(df, p):
    """p = SimpleNamespace 配置"""
    capital = 10000.0
    positions = []
    equity = []
    paused_until = None
    peak = capital
    last_open = None
    R = p.RISK_FREE_RATE

    for date, row in df.iterrows():
        S = float(row["close"])
        iv_raw = float(row["iv"])
        vix = float(row["vix"])
        sma = float(row["sma_100"])
        iv = iv_raw * p.IV_MULTIPLIER   # 双重校准（data.py已×iv_mult，这里再×IV_MULTIPLIER）

        # 1. Portfolio stop
        if positions:
            total_u = 0.0
            for pos in positions:
                dte_r = (pos.expiry_date - date).days
                T = max(dte_r, 0.5) / 365.0
                ip = apply_iv_skew(iv, "put")
                ic_ = apply_iv_skew(iv, "call")
                sp = bs_price(S, pos.K_sp, T, R, ip, "put") - bs_price(S, pos.K_lp, T, R, ip, "put")
                sc = bs_price(S, pos.K_sc, T, R, ic_, "call") - bs_price(S, pos.K_lc, T, R, ic_, "call")
                total_u += (pos.total_prem - sp - sc) * 100 * pos.contracts

            if total_u <= -capital * p.PORTFOLIO_STOP:
                for pos in positions:
                    dte_r = (pos.expiry_date - date).days
                    T = max(dte_r, 0.5) / 365.0
                    ip = apply_iv_skew(iv, "put")
                    ic_ = apply_iv_skew(iv, "call")
                    sp = bs_price(S, pos.K_sp, T, R, ip, "put") - bs_price(S, pos.K_lp, T, R, ip, "put")
                    sc = bs_price(S, pos.K_sc, T, R, ic_, "call") - bs_price(S, pos.K_lc, T, R, ic_, "call")
                    pnl = (pos.total_prem - sp - sc) * 100 * pos.contracts
                    pnl -= pos.contracts * 4 * p.COMMISSION_PER_LEG
                    pnl -= calc_friction_cost(vix) * 100 * pos.contracts
                    capital += pnl
                positions = []
                paused_until = date + pd.Timedelta(days=p.RESUME_AFTER_DAYS)
                equity.append(capital)
                continue

        # 2. Manage positions
        to_close = []
        for j, pos in enumerate(positions):
            dte_r = (pos.expiry_date - date).days
            T = max(dte_r, 0.5) / 365.0
            ip = apply_iv_skew(iv, "put")
            ic_ = apply_iv_skew(iv, "call")
            sp = bs_price(S, pos.K_sp, T, R, ip, "put") - bs_price(S, pos.K_lp, T, R, ip, "put")
            sc = bs_price(S, pos.K_sc, T, R, ic_, "call") - bs_price(S, pos.K_lc, T, R, ic_, "call")
            pnl = (pos.total_prem - sp - sc) * 100 * pos.contracts
            reason = None

            if pnl >= pos.max_profit * p.PROFIT_TARGET:
                reason = "profit"
            elif dte_r <= p.DTE_EXIT:
                if dte_r <= 0:
                    pv = max(pos.K_sp - S, 0) - max(pos.K_lp - S, 0)
                    cv = max(S - pos.K_sc, 0) - max(S - pos.K_lc, 0)
                    pnl = (pos.total_prem - pv - cv) * 100 * pos.contracts
                    reason = "expiry"
                else:
                    reason = "dte"

            if reason:
                pnl -= pos.contracts * 4 * p.COMMISSION_PER_LEG
                if reason != "expiry":
                    pnl -= calc_friction_cost(vix) * 100 * pos.contracts
                capital += pnl
                to_close.append(j)

        for j in sorted(to_close, reverse=True):
            positions.pop(j)

        # 3. Drawdown pause
        if capital > peak:
            peak = capital
        dd_now = (peak - capital) / peak if peak > 0 else 0

        if paused_until and date >= paused_until:
            peak = capital
            paused_until = None
        if paused_until is None and dd_now >= p.MAX_DRAWDOWN_PAUSE:
            paused_until = date + pd.Timedelta(days=p.RESUME_AFTER_DAYS)
        if paused_until and date < paused_until:
            equity.append(capital)
            continue

        # 4. Open
        if last_open and (date - last_open).days < 1:
            equity.append(capital)
            continue

        trend_ok = S > sma
        crisis_vix = getattr(p, 'CRISIS_VIX_THRESHOLD', 999)

        if (len(positions) < p.MAX_POSITIONS
                and p.MIN_VIX <= vix <= p.MAX_VIX
                and vix < crisis_vix
                and trend_ok):

            delta = p.SHORT_PUT_DELTA
            if p.DELTA_VIX_ADJUST and vix > p.DELTA_VIX_THRESHOLD:
                delta = p.DELTA_HIGH_VIX

            T = p.DTE_TARGET / 365.0
            ip = apply_iv_skew(iv, "put")
            ic_ = apply_iv_skew(iv, "call")

            K_sp = find_strike_by_delta(S, T, R, ip, delta, "put", 1.0)
            K_lp = K_sp - p.SPREAD_WIDTH
            K_sc = find_strike_by_delta(S, T, R, ic_, delta, "call", 1.0)
            K_lc = K_sc + p.SPREAD_WIDTH

            if K_sc <= K_sp:
                equity.append(capital)
                continue

            put_prem = spread_value(S, K_sp, K_lp, T, R, ip)
            call_prem = bear_call_spread_value(S, K_sc, K_lc, T, R, ic_)
            total_prem = put_prem + call_prem
            friction = calc_friction_cost(vix)
            net_prem = total_prem - friction

            if net_prem <= 0.05:
                equity.append(capital)
                continue

            max_loss_side = (p.SPREAD_WIDTH - min(put_prem, call_prem)) * 100
            if max_loss_side <= 0:
                equity.append(capital)
                continue
            contracts = max(1, int(capital * p.MAX_RISK_PER_TRADE / max_loss_side))

            capital -= contracts * 4 * p.COMMISSION_PER_LEG
            capital -= friction * 100 * contracts

            positions.append(IC(
                entry_date=date, expiry_date=date + pd.Timedelta(days=p.DTE_TARGET),
                K_sp=K_sp, K_lp=K_lp, K_sc=K_sc, K_lc=K_lc,
                put_prem=put_prem, call_prem=call_prem, total_prem=total_prem,
                contracts=contracts, entry_price=S,
                max_loss=max_loss_side * contracts,
                max_profit=total_prem * 100 * contracts,
            ))
            last_open = date

        equity.append(capital)

    eq = pd.Series(equity, index=df.index[:len(equity)])
    if len(eq) < 100:
        return None
    tr = (eq.iloc[-1] / eq.iloc[0]) - 1
    yrs = (eq.index[-1] - eq.index[0]).days / 365.25
    ann = (1 + tr) ** (1 / yrs) - 1 if yrs > 0 and tr > -1 else -1
    pk = eq.cummax()
    dd = abs(((eq - pk) / pk).min()) * 100
    dr = eq.pct_change().dropna()
    sh = dr.mean() / dr.std() * np.sqrt(252) if dr.std() > 0 else 0
    return {"annual": ann * 100, "dd": dd, "sharpe": sh, "final": eq.iloc[-1]}


# =====================================================================
# 数据下载
# =====================================================================
def dl(sym, iv_mult, start="2005-01-01", end="2024-12-31"):
    ext = pd.Timestamp(start) - pd.Timedelta(days=400)
    px = yf.download(sym, start=ext.strftime("%Y-%m-%d"), end=end, progress=False)
    vx = yf.download("^VIX", start=ext.strftime("%Y-%m-%d"), end=end, progress=False)
    for d in [px, vx]:
        if isinstance(d.columns, pd.MultiIndex):
            d.columns = d.columns.get_level_values(0)
    df = pd.DataFrame(index=px.index)
    df["close"] = px["Close"]
    df["vix"] = vx["Close"].reindex(px.index, method="ffill")
    df["iv"] = df["vix"] / 100.0 * iv_mult
    df["sma_100"] = df["close"].rolling(100).mean()
    df = df.loc[start:end].copy()
    df.dropna(inplace=True)
    return df


def make_cfg(**kw):
    c = types.SimpleNamespace()
    for a in dir(base_cfg):
        if not a.startswith("_"):
            setattr(c, a, getattr(base_cfg, a))
    for k, v in kw.items():
        setattr(c, k, v)
    return c


# =====================================================================
# 主程序
# =====================================================================
def main():
    print("=" * 70)
    print("快速策略扫描 — 年化≥20% + 最大回撤≤10%")
    print("=" * 70)

    # 标的（仅ETF，个股风险过大）
    targets = {
        "SPY":  0.95,
        "QQQ":  1.11,
        "IWM":  1.22,
        "DIA":  0.76,
        "TLT":  0.85,
        "GLD":  0.90,
        "EEM":  1.15,
        "XLF":  1.05,
    }

    # 精简参数网格 — 聚焦有效区间
    DELTAS       = [0.20, 0.25, 0.30]
    SPREADS      = [3, 5, 7]
    MAX_POSES    = [3, 4]
    DTES         = [5, 7, 10]
    PROFIT_TGTS  = [0.35, 0.40, 0.50]
    MAX_VIXS     = [22, 25]
    RISKS        = [0.02, 0.025]

    n_total = (len(targets) * len(DELTAS) * len(SPREADS) * len(MAX_POSES)
               * len(DTES) * len(PROFIT_TGTS) * len(MAX_VIXS) * len(RISKS))
    print(f"标的: {len(targets)}  参数组合: {n_total:,}\n")

    winning = []
    tested = 0

    for sym, iv_mult in targets.items():
        print(f"{'─'*50}  {sym} (IV_MULT={iv_mult})")
        df = dl(sym, iv_mult)
        if len(df) < 500:
            print("  ⚠ 数据不足")
            continue
        print(f"  数据: {df.index[0].date()}~{df.index[-1].date()} {len(df)}天")

        best_score = 0
        for delta in DELTAS:
          for spread in SPREADS:
            for max_pos in MAX_POSES:
              for dte in DTES:
                for pt in PROFIT_TGTS:
                  for max_vix in MAX_VIXS:
                    for risk in RISKS:
                        tested += 1
                        cfg = make_cfg(
                            SHORT_PUT_DELTA=delta, SPREAD_WIDTH=spread,
                            MAX_POSITIONS=max_pos, DTE_TARGET=dte,
                            DTE_EXIT=1, PROFIT_TARGET=pt,
                            MAX_VIX=max_vix, MAX_RISK_PER_TRADE=risk,
                            IV_MULTIPLIER=iv_mult,
                        )
                        try:
                            r = run_bt(df, cfg)
                        except Exception:
                            continue
                        if r is None:
                            continue

                        if r["annual"] >= 20 and r["dd"] <= 10:
                            score = (min(r["annual"]/20.0, 1.5)*50
                                     + min(10.0/max(r["dd"], 0.1), 1.5)*50)
                            entry = dict(symbol=sym, delta=delta, spread=spread,
                                         max_pos=max_pos, dte=dte, pt=pt,
                                         max_vix=max_vix, risk=risk,
                                         annual=r["annual"], dd=r["dd"],
                                         sharpe=r["sharpe"], final=r["final"],
                                         score=score)
                            winning.append(entry)
                            if score > best_score:
                                best_score = score
                                print(f"  ✅ d{delta} s{spread} p{max_pos} dte{dte} pt{pt} vix{max_vix} r{risk}"
                                      f" → {r['annual']:.1f}%/DD{r['dd']:.1f}%/Sh{r['sharpe']:.2f} ★{score:.1f}")

        if best_score == 0:
            print("  ❌ 无达标")

    print(f"\n{'='*70}")
    print(f"完成 | 测试: {tested:,} | 达标: {len(winning)}")

    if not winning:
        print("❌ 无达标策略")
        return

    winning.sort(key=lambda x: x["score"], reverse=True)

    # ── TOP20 ────────────────────────────────────────────────────
    print(f"\nTOP 20 (年化≥20%, 回撤≤10%)")
    print(f"{'#':<3} {'标的':<5} {'δ':>5} {'宽':>3} {'仓':>3} {'DTE':>4} {'PT':>5} {'VIX':>4} {'风险':>5} "
          f"{'年化':>7} {'回撤':>7} {'夏普':>6} {'★':>6}")
    print("─" * 80)
    for i, r in enumerate(winning[:20]):
        print(f"{i+1:<3} {r['symbol']:<5} {r['delta']:>5} ${r['spread']:<2} {r['max_pos']:>3} {r['dte']:>4} "
              f"{r['pt']:>5} {r['max_vix']:>4} {r['risk']:>5} "
              f"{r['annual']:>6.1f}% {-r['dd']:>6.1f}% {r['sharpe']:>6.2f} {r['score']:>6.1f}")

    # ── 各标的最优 ────────────────────────────────────────────────
    by_sym = {}
    for r in winning:
        if r["symbol"] not in by_sym or r["score"] > by_sym[r["symbol"]]["score"]:
            by_sym[r["symbol"]] = r

    print(f"\n{'='*70}")
    print("各标的最优策略（可实操）")
    print(f"{'='*70}")

    for r in sorted(by_sym.values(), key=lambda x: x["score"], reverse=True):
        print(f"""
┌─ 【{r['symbol']}】Iron Condor
│  年化: {r['annual']:.2f}%  回撤: -{r['dd']:.2f}%  夏普: {r['sharpe']:.2f}  ★{r['score']:.1f}
│  $10,000 → ${r['final']:,.0f}（2005-2024）
│  参数: Delta={r['delta']}  价差=${r['spread']}  仓位={r['max_pos']}  DTE={r['dte']}天
│        盈利目标={r['pt']*100:.0f}%  VIX上限={r['max_vix']}  单笔风险={r['risk']*100:.1f}%
└────────────────────────────────────────────────────""")

    # 保存
    out = os.path.join(os.path.dirname(__file__), "winning_strategies.csv")
    pd.DataFrame(winning).to_csv(out, index=False)
    print(f"\n✅ 完整结果已保存: {out}")

    best = winning[0]
    print(f"\n{'='*70}")
    print("★★★ 最优推荐")
    print(f"{'='*70}")
    print(f"  {best['symbol']}  Iron Condor")
    print(f"  年化: {best['annual']:.2f}%  回撤: -{best['dd']:.2f}%  夏普: {best['sharpe']:.2f}")
    print(f"  $10,000 → ${best['final']:,.0f}（20年）")
    print(f"  Delta={best['delta']}  宽度=${best['spread']}  仓位={best['max_pos']}  DTE={best['dte']}  PT={best['pt']*100:.0f}%  VIX≤{best['max_vix']}")


if __name__ == "__main__":
    main()
