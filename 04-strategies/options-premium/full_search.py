#!/usr/bin/env python3
"""
全面策略搜索 — 穷举所有可能的参数组合
目标: 年化≥20%，最大回撤≤10%
"""
import sys, os, itertools
import pandas as pd
import numpy as np
import yfinance as yf
from dataclasses import dataclass

sys.path.insert(0, os.path.dirname(__file__))
from pricing import apply_iv_skew, calc_friction_cost, spread_value, bear_call_spread_value, find_strike_by_delta


# ==============================================================
# 数据缓存
# ==============================================================
_data_cache = {}

def get_data(symbol, start="2005-01-01", end="2024-12-31", iv_mult=0.95):
    key = (symbol, start, end, iv_mult)
    if key in _data_cache:
        return _data_cache[key]

    ext_start = pd.Timestamp(start) - pd.Timedelta(days=400)
    px = yf.download(symbol, start=ext_start.strftime("%Y-%m-%d"), end=end, progress=False)
    vix = yf.download("^VIX", start=ext_start.strftime("%Y-%m-%d"), end=end, progress=False)

    for d in [px, vix]:
        if isinstance(d.columns, pd.MultiIndex):
            d.columns = d.columns.get_level_values(0)

    df = pd.DataFrame(index=px.index)
    df["close"] = px["Close"]
    df["vix"] = vix["Close"].reindex(px.index, method="ffill")
    df["returns"] = df["close"].pct_change()
    df["iv"] = df["vix"] / 100.0 * iv_mult
    df["sma_100"] = df["close"].rolling(100).mean()
    df["sma_50"] = df["close"].rolling(50).mean()
    df = df.loc[start:end].copy()
    df.dropna(inplace=True)
    _data_cache[key] = df
    return df


# ==============================================================
# 回测引擎（同时支持 Iron Condor 和 Put Spread）
# ==============================================================
@dataclass
class Pos:
    expiry: object
    Ksp: float; Klp: float
    Ksc: float = 0; Klc: float = 0
    prem: float = 0; max_profit: float = 0; max_loss: float = 0
    contracts: int = 1; iv: float = 0
    strategy: str = "ic"


def run(df, delta=0.30, spread=5, max_pos=4, risk_pct=0.025,
        profit_target=0.40, port_stop=0.03, dd_pause=0.04,
        resume_days=10, min_vix=10, max_vix=25, dte=7,
        delta_high=0.10, delta_thresh=22, iv_skew_put=1.30,
        iv_skew_call=0.95, commission=0.65, bid_ask=0.03,
        slippage=0.01, crisis_vix=30, capital=10000,
        strategy_type="iron_condor"):

    positions = []
    equity_list = []
    peak = capital
    paused_until = None
    last_open = None
    r = 0.05

    for date, row in df.iterrows():
        S = row["close"]
        iv_base = row["iv"]
        vix = row["vix"]
        sma = row["sma_100"]

        # 1. Portfolio stop
        if positions:
            total_u = 0
            for p in positions:
                dte_r = max((p.expiry - date).days, 0.5)
                T = dte_r / 365.0
                ivp = apply_iv_skew(iv_base, "put")
                ivc = apply_iv_skew(iv_base, "call")
                psv = spread_value(S, p.Ksp, p.Klp, T, r, ivp)
                if p.strategy == "ic":
                    csv = bear_call_spread_value(S, p.Ksc, p.Klc, T, r, ivc)
                else:
                    csv = 0
                cur = (psv + csv) * 100 * p.contracts
                ent = p.prem * 100 * p.contracts
                total_u += ent - cur

            if total_u <= -capital * port_stop:
                n = len(positions)
                legs = 8 if strategy_type == "iron_condor" else 4
                comm = n * legs * commission
                capital += total_u - comm
                positions = []
                paused_until = date + pd.Timedelta(days=resume_days)
                equity_list.append(capital)
                continue

        # 2. Manage positions
        to_close = []
        for j, p in enumerate(positions):
            dte_r = max((p.expiry - date).days, 0.5)
            T = dte_r / 365.0
            ivp = apply_iv_skew(iv_base, "put")
            ivc = apply_iv_skew(iv_base, "call")
            psv = spread_value(S, p.Ksp, p.Klp, T, r, ivp)
            if p.strategy == "ic":
                csv = bear_call_spread_value(S, p.Ksc, p.Klc, T, r, ivc)
            else:
                csv = 0
            cur_prem = psv + csv
            pnl = (p.prem - cur_prem) * 100 * p.contracts
            close_reason = None
            if pnl >= p.max_profit * profit_target:
                close_reason = "profit"
            elif (p.expiry - date).days <= 1:
                close_reason = "dte"

            if close_reason:
                legs = 8 if p.strategy == "ic" else 4
                friction = (bid_ask + slippage) * 100 * p.contracts
                if vix > crisis_vix:
                    friction *= 3
                comm = legs * commission
                net = pnl - friction - comm
                capital += net
                to_close.append(j)

        for j in sorted(to_close, reverse=True):
            positions.pop(j)

        # 3. Drawdown pause
        if capital > peak:
            peak = capital
        dd_now = (peak - capital) / peak if peak > 0 else 0

        if dd_now >= dd_pause and paused_until is None:
            paused_until = date + pd.Timedelta(days=resume_days)

        if paused_until and date >= paused_until:
            peak = capital
            paused_until = None

        if paused_until:
            equity_list.append(capital)
            continue

        # 4. Open new positions
        if last_open and (date - last_open).days < 1:
            equity_list.append(capital)
            continue

        trend_ok = S > sma
        crisis = vix > crisis_vix

        can_open = (
            len(positions) < max_pos
            and vix >= min_vix
            and vix <= max_vix
            and trend_ok
            and not crisis
        )

        if can_open:
            d = delta if vix <= delta_thresh else delta_high
            ivp = apply_iv_skew(iv_base, "put")
            ivc = apply_iv_skew(iv_base, "call")
            T = dte / 365.0

            Ksp = find_strike_by_delta(S, T, r, ivp, d, "put", 1.0)
            Klp = Ksp - spread

            if strategy_type == "iron_condor":
                Ksc = find_strike_by_delta(S, T, r, ivc, d, "call", 1.0)
                Klc = Ksc + spread
                if Ksc <= Ksp:
                    equity_list.append(capital)
                    continue
                put_prem = spread_value(S, Ksp, Klp, T, r, ivp)
                call_prem = bear_call_spread_value(S, Ksc, Klc, T, r, ivc)
                total_prem = put_prem + call_prem
            else:
                # Put Spread Only
                Ksc, Klc = 0, 0
                total_prem = spread_value(S, Ksp, Klp, T, r, ivp)

            if total_prem <= 0.02:
                equity_list.append(capital)
                continue

            max_loss_per = (spread - total_prem) * 100
            if max_loss_per <= 0 or np.isnan(max_loss_per) or capital <= 0:
                equity_list.append(capital)
                continue

            contracts = max(1, int(capital * risk_pct / max_loss_per))
            legs = 8 if strategy_type == "iron_condor" else 4
            friction = (bid_ask + slippage) * 100 * contracts
            if vix > crisis_vix:
                friction *= 3
            comm = legs * commission
            net_prem = total_prem * 100 * contracts - friction - comm

            if net_prem <= 0:
                equity_list.append(capital)
                continue

            pos = Pos(
                expiry=date + pd.Timedelta(days=dte),
                Ksp=Ksp, Klp=Klp, Ksc=Ksc, Klc=Klc,
                prem=total_prem,
                max_profit=net_prem,
                max_loss=max_loss_per * contracts + friction + comm,
                contracts=contracts, iv=iv_base,
                strategy=strategy_type[:2],
            )
            positions.append(pos)
            last_open = date

        equity_list.append(capital)

    # Metrics
    eq = pd.Series(equity_list, index=df.index[:len(equity_list)])
    total_ret = (capital - 10000) / 10000
    years = len(df) / 252
    annual = (1 + total_ret) ** (1 / years) - 1 if years > 0 and total_ret > -1 else -1
    peak_s = eq.expanding().max()
    dd = abs((eq - peak_s) / peak_s).max() * 100
    daily_r = eq.pct_change().dropna()
    sharpe = daily_r.mean() / daily_r.std() * np.sqrt(252) if daily_r.std() > 0 else 0

    return annual * 100, dd, sharpe, capital


# ==============================================================
# 主搜索
# ==============================================================
def main():
    print("=" * 80)
    print("全面策略搜索 — 年化≥20% + 最大回撤≤10%")
    print("=" * 80)

    # 标的列表：ETF优先（分散化好）
    symbols = {
        "SPY":  0.95,   # S&P500
        "QQQ":  1.11,   # Nasdaq100
        "IWM":  1.22,   # Russell2000
        "DIA":  0.76,   # Dow Jones
        "GLD":  0.90,   # 黄金
        "XLF":  1.05,   # 金融
        "XLE":  1.10,   # 能源
        "EEM":  1.15,   # 新兴市场
    }

    # 参数网格
    param_grid = {
        "delta":         [0.20, 0.25, 0.30],
        "spread":        [3, 5, 7],
        "max_pos":       [2, 3, 4],
        "risk_pct":      [0.02, 0.025],
        "dte":           [5, 7, 10, 14],
        "profit_target": [0.35, 0.40, 0.50],
        "max_vix":       [22, 25, 30],
        "strategy_type": ["iron_condor", "put_spread"],
    }

    winning = []
    tested = 0

    for sym, iv_mult in symbols.items():
        print(f"\n{'='*60}")
        print(f"标的: {sym} (IV_MULT={iv_mult})")
        print(f"{'='*60}")

        df = get_data(sym, iv_mult=iv_mult)
        if df is None or len(df) < 500:
            print(f"  数据不足，跳过")
            continue
        print(f"  数据: {df.index[0].date()} ~ {df.index[-1].date()} ({len(df)}天)")

        # 重新调整df['iv']为per-symbol校准
        df_sym = df.copy()
        df_sym["iv"] = df_sym["vix"] / 100.0 * iv_mult

        best_score_sym = 0

        for delta, spread, max_pos, risk_pct, dte, profit_target, max_vix, stype in itertools.product(
            param_grid["delta"], param_grid["spread"], param_grid["max_pos"],
            param_grid["risk_pct"], param_grid["dte"], param_grid["profit_target"],
            param_grid["max_vix"], param_grid["strategy_type"]
        ):
            tested += 1
            try:
                annual, dd, sharpe, final_eq = run(
                    df_sym, delta=delta, spread=spread, max_pos=max_pos,
                    risk_pct=risk_pct, profit_target=profit_target,
                    max_vix=max_vix, dte=dte,
                    strategy_type=stype,
                )
            except Exception as e:
                continue

            if annual >= 20 and dd <= 10:
                score = min(annual / 20.0, 1.5) * 50 + min(10.0 / max(dd, 0.1), 1.5) * 50
                result = {
                    "symbol": sym, "strategy": stype, "delta": delta,
                    "spread": spread, "max_pos": max_pos, "risk_pct": risk_pct,
                    "dte": dte, "profit_target": profit_target, "max_vix": max_vix,
                    "annual": annual, "dd": dd, "sharpe": sharpe,
                    "final_eq": final_eq, "score": score
                }
                winning.append(result)
                if score > best_score_sym:
                    best_score_sym = score
                    print(f"  ✅ 新纪录: {stype} d{delta} s{spread} p{max_pos} dte{dte} pt{profit_target} vix{max_vix}"
                          f" → 年化{annual:.1f}% DD{dd:.1f}% 夏普{sharpe:.2f} SCORE{score:.1f}")

    print(f"\n\n{'='*80}")
    print(f"搜索完成 | 总测试: {tested} | 达标策略: {len(winning)}")
    print(f"{'='*80}")

    if not winning:
        print("❌ 未找到达标策略")
        return

    # 排序并输出
    winning.sort(key=lambda x: x["score"], reverse=True)

    print(f"\n{'='*80}")
    print("TOP 20 达标策略 (年化≥20% + 最大回撤≤10%)")
    print(f"{'='*80}")
    header = f"{'#':<3} {'标的':<5} {'类型':<12} {'Delta':<6} {'宽度':<5} {'仓位':<5} {'DTE':<5} {'PT':<5} {'VIX':<5} {'年化':>7} {'回撤':>7} {'夏普':>6} {'SCORE':>7}"
    print(header)
    print("-" * 90)

    for i, r in enumerate(winning[:20]):
        stype_short = "IC" if r["strategy"] == "iron_condor" else "PS"
        print(f"{i+1:<3} {r['symbol']:<5} {stype_short:<12} {r['delta']:<6} ${r['spread']:<4} {r['max_pos']:<5} "
              f"{r['dte']:<5} {r['profit_target']:<5} {r['max_vix']:<5} "
              f"{r['annual']:>6.1f}% {-r['dd']:>6.1f}% {r['sharpe']:>6.2f} {r['score']:>7.1f}")

    # 按标的汇总最佳策略
    print(f"\n{'='*80}")
    print("各标的最佳策略汇总")
    print(f"{'='*80}")

    by_sym = {}
    for r in winning:
        if r["symbol"] not in by_sym or r["score"] > by_sym[r["symbol"]]["score"]:
            by_sym[r["symbol"]] = r

    for sym, r in sorted(by_sym.items(), key=lambda x: x[1]["score"], reverse=True):
        stype = "Iron Condor" if r["strategy"] == "iron_condor" else "Put Spread"
        print(f"\n【{sym}】{stype}")
        print(f"  年化收益: {r['annual']:.2f}%  最大回撤: -{r['dd']:.2f}%  夏普比率: {r['sharpe']:.2f}")
        print(f"  参数: Delta={r['delta']} 宽度=${r['spread']} 仓位={r['max_pos']}  DTE={r['dte']}天  盈利目标={r['profit_target']*100:.0f}%  VIX上限={r['max_vix']}")
        print(f"  $10,000 → ${r['final_eq']:,.0f} (20年)")
        print(f"  SCORE: {r['score']:.1f}")

    # 保存结果
    df_results = pd.DataFrame(winning)
    out_path = os.path.join(os.path.dirname(__file__), "search_results.csv")
    df_results.to_csv(out_path, index=False)
    print(f"\n结果已保存: {out_path}")

    # 最终推荐
    best = winning[0]
    print(f"\n{'='*80}")
    print("★ 最优策略推荐")
    print(f"{'='*80}")
    stype = "Iron Condor (铁鹰)" if best["strategy"] == "iron_condor" else "Bull Put Spread (牛市价差)"
    print(f"  标的:       {best['symbol']}")
    print(f"  策略类型:   {stype}")
    print(f"  短腿Delta:  {best['delta']} (VIX>{22}时用0.10保守)")
    print(f"  价差宽度:   ${best['spread']}")
    print(f"  最大仓位:   {best['max_pos']}个同时持有")
    print(f"  到期天数:   {best['dte']}天")
    print(f"  盈利目标:   {best['profit_target']*100:.0f}%最大盈利时平仓")
    print(f"  VIX上限:    {best['max_vix']} (VIX>{best['max_vix']}停止开新仓)")
    print(f"")
    print(f"  年化收益:   {best['annual']:.2f}%  ✅")
    print(f"  最大回撤:   -{best['dd']:.2f}%  ✅")
    print(f"  夏普比率:   {best['sharpe']:.2f}")
    print(f"  $10,000成长为: ${best['final_eq']:,.0f} (20年, 2005-2024)")


if __name__ == "__main__":
    main()
