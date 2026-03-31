"""
策略发现引擎 — 用 IBKR 真实 IV 数据驱动
对 25 个标的 × 多种策略配置 做全面回测
找出所有能达到 年化≥20% + 回撤≤10% 的组合
"""
import sys, os
import pandas as pd
import numpy as np
import yfinance as yf
from dataclasses import dataclass
from typing import List

sys.path.insert(0, os.path.dirname(__file__))
from pricing import bs_price, bs_delta, find_strike_by_delta, apply_iv_skew
from pricing import spread_value, bear_call_spread_value, calc_friction_cost


def get_iv_vix_ratio(symbol):
    """从 IBKR 数据计算 IV/VIX 比率"""
    iv_file = f"ibkr_data/{symbol.lower()}_iv_history.csv"
    if not os.path.exists(iv_file):
        return None
    iv_df = pd.read_csv(iv_file)
    iv_df['date'] = pd.to_datetime(iv_df['date'])
    iv_df = iv_df.set_index('date')

    vix = yf.download("^VIX", start=iv_df.index[0].strftime('%Y-%m-%d'),
                       end=iv_df.index[-1].strftime('%Y-%m-%d'), progress=False)
    if isinstance(vix.columns, pd.MultiIndex):
        vix.columns = vix.columns.get_level_values(0)
    vix.index = vix.index.tz_localize(None)

    merged = pd.DataFrame({'real_iv': iv_df['close'], 'vix': vix['Close']}).dropna()
    if len(merged) > 100:
        return (merged['real_iv'] / (merged['vix'] / 100)).mean()
    return None


def fetch_data(symbol, start="2010-01-01", end="2024-12-31", iv_mult=1.0):
    """获取回测数据"""
    ext_start = pd.Timestamp(start) - pd.Timedelta(days=400)
    px = yf.download(symbol, start=ext_start.strftime("%Y-%m-%d"), end=end, progress=False)
    vix = yf.download("^VIX", start=ext_start.strftime("%Y-%m-%d"), end=end, progress=False)

    for d in [px, vix]:
        if isinstance(d.columns, pd.MultiIndex):
            d.columns = d.columns.get_level_values(0)

    df = pd.DataFrame(index=px.index)
    df["close"] = px["Close"]
    df["high"] = px["High"]
    df["low"] = px["Low"]
    df["vix"] = vix["Close"].reindex(px.index, method="ffill")
    df["returns"] = df["close"].pct_change()
    df["iv"] = df["vix"] / 100.0 * iv_mult
    df["sma_100"] = df["close"].rolling(100).mean()
    df["sma_50"] = df["close"].rolling(50).mean()
    df = df.loc[start:end].copy()
    df.dropna(inplace=True)
    return df


@dataclass
class IC:
    entry_date: object
    expiry_date: object
    S: float
    Ksp: float; Klp: float; Ksc: float; Klc: float
    prem: float; max_profit: float; max_loss: float
    contracts: int; iv: float


def backtest(df, symbol, delta=0.30, spread=5, max_pos=4, risk_pct=0.025,
             profit_target=0.40, portfolio_stop=0.03, dd_pause=0.04,
             resume_days=10, min_vix=10, max_vix=25, dte=7,
             delta_high=0.10, delta_thresh=22, iv_skew_put=1.30,
             iv_skew_call=0.95, commission=0.65, bid_ask=0.03,
             slippage=0.01, crisis_vix=30, capital=10000,
             strategy_type="iron_condor"):
    """通用回测"""
    positions = []
    closed = []
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

        # Portfolio stop
        if positions:
            total_u = 0
            for p in positions:
                dte_r = max((p.expiry_date - date).days, 0.5)
                T = dte_r / 365.0
                ivp = iv_base * iv_skew_put
                ivc = iv_base * iv_skew_call

                if strategy_type == "iron_condor":
                    cur = spread_value(S, p.Ksp, p.Klp, T, r, ivp) + \
                          bear_call_spread_value(S, p.Ksc, p.Klc, T, r, ivc)
                else:  # put_spread
                    cur = spread_value(S, p.Ksp, p.Klp, T, r, ivp)

                pnl = (p.prem - cur) * 100 * p.contracts
                total_u += pnl

            if total_u <= -capital * portfolio_stop:
                comm = len(positions) * (8 if strategy_type == "iron_condor" else 4) * commission
                capital += total_u - comm
                for p in positions:
                    closed.append(total_u / len(positions))
                positions = []
                paused_until = date + pd.Timedelta(days=resume_days)
                equity_list.append(capital)
                continue

        # Manage positions
        to_close = []
        for j, p in enumerate(positions):
            dte_r = max((p.expiry_date - date).days, 0.5)
            T = dte_r / 365.0
            ivp = iv_base * iv_skew_put
            ivc = iv_base * iv_skew_call

            if strategy_type == "iron_condor":
                cur = spread_value(S, p.Ksp, p.Klp, T, r, ivp) + \
                      bear_call_spread_value(S, p.Ksc, p.Klc, T, r, ivc)
            else:
                cur = spread_value(S, p.Ksp, p.Klp, T, r, ivp)

            pnl = (p.prem - cur) * 100 * p.contracts
            reason = None

            if pnl >= p.max_profit * profit_target:
                reason = "tp"
            elif dte_r <= 1:
                reason = "dte"

            if reason:
                fric = (bid_ask + slippage) * 100 * p.contracts
                legs = 8 if strategy_type == "iron_condor" else 4
                comm = legs * commission
                net = pnl - fric - comm
                capital += net
                closed.append(net)
                to_close.append(j)

        for j in sorted(to_close, reverse=True):
            positions.pop(j)

        # Drawdown
        if capital > peak:
            peak = capital
        dd = (peak - capital) / peak if peak > 0 else 0

        if dd >= dd_pause and paused_until is None:
            paused_until = date + pd.Timedelta(days=resume_days)

        if paused_until and date >= paused_until:
            peak = capital
            paused_until = None

        if paused_until:
            equity_list.append(capital)
            continue

        # Open new
        if last_open and (date - last_open).days < 1:
            equity_list.append(capital)
            continue

        can_open = (
            len(positions) < max_pos
            and vix >= min_vix and vix <= max_vix
            and S > sma
            and vix < crisis_vix
            and capital > 0
        )

        if can_open:
            d = delta if vix <= delta_thresh else delta_high
            ivp = iv_base * iv_skew_put
            ivc = iv_base * iv_skew_call
            T = dte / 365.0

            Ksp = find_strike_by_delta(S, T, r, ivp, d, "put", 1.0)
            Klp = Ksp - spread

            if strategy_type == "iron_condor":
                Ksc = find_strike_by_delta(S, T, r, ivc, d, "call", 1.0)
                Klc = Ksc + spread
                if Ksc <= Ksp:
                    equity_list.append(capital)
                    continue
                prem = spread_value(S, Ksp, Klp, T, r, ivp) + \
                       bear_call_spread_value(S, Ksc, Klc, T, r, ivc)
            else:  # put_spread only
                Ksc = Klc = 0
                prem = spread_value(S, Ksp, Klp, T, r, ivp)

            if prem <= 0.02 or np.isnan(prem):
                equity_list.append(capital)
                continue

            max_loss_per = (spread - prem) * 100
            if max_loss_per <= 0 or np.isnan(max_loss_per):
                equity_list.append(capital)
                continue

            contracts = max(1, int(capital * risk_pct / max_loss_per))
            fric = (bid_ask + slippage) * 100 * contracts
            legs = 8 if strategy_type == "iron_condor" else 4
            comm = legs * commission
            net_prem = prem * 100 * contracts - fric - comm

            if net_prem <= 0:
                equity_list.append(capital)
                continue

            positions.append(IC(
                entry_date=date, expiry_date=date + pd.Timedelta(days=dte),
                S=S, Ksp=Ksp, Klp=Klp, Ksc=Ksc, Klc=Klc,
                prem=prem, max_profit=net_prem,
                max_loss=max_loss_per * contracts + fric + comm,
                contracts=contracts, iv=iv_base
            ))
            last_open = date

        equity_list.append(capital)

    # Metrics
    init = 10000
    total_ret = (capital - init) / init
    years = len(df) / 252
    if total_ret > -1 and years > 0:
        annual = (1 + total_ret) ** (1 / years) - 1
    else:
        annual = -1

    eq = pd.Series(equity_list[:len(df)], index=df.index[:len(equity_list)])
    peak_eq = eq.expanding().max()
    dd_series = (eq - peak_eq) / peak_eq
    max_dd = abs(dd_series.min()) * 100

    daily_ret = eq.pct_change().dropna()
    sharpe = daily_ret.mean() / daily_ret.std() * np.sqrt(252) if daily_ret.std() > 0 else 0

    wins = [p for p in closed if p > 0]
    losses = [p for p in closed if p <= 0]
    win_rate = len(wins) / len(closed) * 100 if closed else 0

    return {
        "symbol": symbol,
        "strategy": strategy_type,
        "annual": annual * 100,
        "max_dd": max_dd,
        "sharpe": sharpe,
        "trades": len(closed),
        "win_rate": win_rate,
        "final": capital,
        "delta": delta,
        "spread": spread,
        "max_pos": max_pos,
    }


if __name__ == "__main__":
    print("=" * 80)
    print("策略发现引擎 — IBKR 真实 IV 数据驱动")
    print("目标: 年化≥20%, 最大回撤≤10%")
    print("=" * 80)

    # 所有候选标的
    all_symbols = [
        'SPY', 'QQQ', 'IWM', 'DIA',
        'XLF', 'XLE', 'XLK', 'XLV', 'XLU', 'XBI',
        'GLD', 'SLV', 'TLT', 'HYG', 'EEM', 'EFA',
        'AAPL', 'MSFT', 'GOOGL', 'AMZN', 'NVDA', 'META', 'TSLA',
    ]

    # 计算 IV/VIX 比率
    print("\n--- IV/VIX 比率 ---")
    ratios = {}
    for sym in all_symbols:
        r = get_iv_vix_ratio(sym)
        if r:
            ratios[sym] = r
            print(f"  {sym:6s}: {r:.4f}")

    # 策略配置空间
    configs = [
        # Iron Condor 变体
        {"strategy_type": "iron_condor", "delta": 0.30, "spread": 5, "max_pos": 4, "risk_pct": 0.025, "label": "IC d30 w5 p4"},
        {"strategy_type": "iron_condor", "delta": 0.25, "spread": 5, "max_pos": 4, "risk_pct": 0.025, "label": "IC d25 w5 p4"},
        {"strategy_type": "iron_condor", "delta": 0.20, "spread": 5, "max_pos": 3, "risk_pct": 0.02, "label": "IC d20 w5 p3"},
        {"strategy_type": "iron_condor", "delta": 0.30, "spread": 3, "max_pos": 5, "risk_pct": 0.02, "label": "IC d30 w3 p5"},
        {"strategy_type": "iron_condor", "delta": 0.35, "spread": 5, "max_pos": 3, "risk_pct": 0.02, "label": "IC d35 w5 p3"},
        # Put Spread Only (看涨偏向)
        {"strategy_type": "put_spread", "delta": 0.30, "spread": 5, "max_pos": 4, "risk_pct": 0.025, "label": "PS d30 w5 p4"},
        {"strategy_type": "put_spread", "delta": 0.25, "spread": 5, "max_pos": 5, "risk_pct": 0.02, "label": "PS d25 w5 p5"},
        {"strategy_type": "put_spread", "delta": 0.20, "spread": 5, "max_pos": 5, "risk_pct": 0.025, "label": "PS d20 w5 p5"},
        {"strategy_type": "put_spread", "delta": 0.20, "spread": 3, "max_pos": 6, "risk_pct": 0.02, "label": "PS d20 w3 p6"},
    ]

    all_results = []

    for sym in all_symbols:
        ratio = ratios.get(sym, 1.0)
        iv_mult = 0.95 * ratio  # IBKR 校准

        # 跳过明显不适合的（IV/VIX > 2.5 的极高波动标的）
        if ratio > 2.5:
            print(f"\n⏭️  {sym} 跳过 (IV/VIX={ratio:.2f} 太高)")
            continue

        try:
            df = fetch_data(sym, start="2010-01-01", end="2024-12-31", iv_mult=iv_mult)
        except Exception as e:
            print(f"\n❌ {sym} 数据获取失败: {e}")
            continue

        if len(df) < 500:
            print(f"\n⏭️  {sym} 数据不足 ({len(df)}天)")
            continue

        print(f"\n{'='*60}")
        print(f"{sym} (IV/VIX={ratio:.2f}, IV_mult={iv_mult:.3f}, {len(df)}天)")
        print(f"{'='*60}")

        for cfg in configs:
            # 高 IV 标的调整 bid-ask
            ba = 0.03 if ratio < 1.5 else 0.05
            slip = 0.01 if ratio < 1.5 else 0.02

            result = backtest(
                df, sym,
                delta=cfg["delta"], spread=cfg["spread"],
                max_pos=cfg["max_pos"], risk_pct=cfg["risk_pct"],
                strategy_type=cfg["strategy_type"],
                iv_skew_put=1.30 if ratio < 1.5 else 1.20,
                iv_skew_call=0.95,
                bid_ask=ba, slippage=slip,
            )
            result["config"] = cfg["label"]
            result["iv_ratio"] = ratio
            all_results.append(result)

            flag = "✅" if result["annual"] >= 20 and result["max_dd"] <= 10 else ""
            if result["annual"] > 10:  # 只显示有潜力的
                print(f"  {cfg['label']:18s} 年化={result['annual']:>7.2f}% 回撤={-result['max_dd']:>7.2f}% "
                      f"夏普={result['sharpe']:>5.2f} 交易={result['trades']:>5} 胜率={result['win_rate']:>5.1f}% {flag}")

    # 排行榜
    print(f"\n{'='*80}")
    print("🏆 达标策略排行榜 (年化≥20% & 回撤≤10%)")
    print(f"{'='*80}")

    qualified = [r for r in all_results if r["annual"] >= 20 and r["max_dd"] <= 10]
    qualified.sort(key=lambda x: x["annual"], reverse=True)

    if qualified:
        print(f"{'标的':<7} {'策略':<20} {'年化':>8} {'回撤':>8} {'夏普':>6} {'交易':>6} {'胜率':>6}")
        print("-" * 80)
        for r in qualified:
            print(f"{r['symbol']:<7} {r['config']:<20} {r['annual']:>7.2f}% {-r['max_dd']:>7.2f}% "
                  f"{r['sharpe']:>6.2f} {r['trades']:>6} {r['win_rate']:>5.1f}%")
    else:
        print("❌ 没有组合能同时满足 年化≥20% 和 回撤≤10%")
        print("\n接近达标的（年化≥15% 或 回撤≤12%）:")
        near = [r for r in all_results if r["annual"] >= 15 or (r["annual"] >= 10 and r["max_dd"] <= 12)]
        near.sort(key=lambda x: x["annual"] - r["max_dd"], reverse=True)
        print(f"{'标的':<7} {'策略':<20} {'年化':>8} {'回撤':>8} {'夏普':>6} {'交易':>6} {'胜率':>6}")
        print("-" * 80)
        for r in near[:20]:
            flag = "✅" if r["annual"] >= 20 and r["max_dd"] <= 10 else "⚠️"
            print(f"{r['symbol']:<7} {r['config']:<20} {r['annual']:>7.2f}% {-r['max_dd']:>7.2f}% "
                  f"{r['sharpe']:>6.2f} {r['trades']:>6} {r['win_rate']:>5.1f}% {flag}")

    # 保存全部结果
    pd.DataFrame(all_results).to_csv("ibkr_data/strategy_discovery_results.csv", index=False)
    print(f"\n💾 全部 {len(all_results)} 个结果已保存")
