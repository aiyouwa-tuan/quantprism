"""
多标的回测引擎
使用 IBKR 真实 IV 数据 + yfinance 价格回测 SPY/QQQ/M7
"""
import sys, os
import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime

# 添加路径
sys.path.insert(0, os.path.dirname(__file__))
from pricing import bs_price, bs_delta, find_strike_by_delta, apply_iv_skew, calc_friction_cost
from pricing import spread_value, bear_call_spread_value
from dataclasses import dataclass
from typing import List, Optional

# ============================================================
# 配置
# ============================================================
@dataclass
class StrategyConfig:
    symbol: str
    initial_capital: float = 10000
    short_put_delta: float = 0.30
    delta_high_vix: float = 0.10
    delta_vix_threshold: float = 22
    spread_width: float = 5
    dte_target: int = 7
    max_positions: int = 4
    max_risk_per_trade: float = 0.025
    commission_per_leg: float = 0.65
    profit_target: float = 0.40
    dte_exit: int = 1
    portfolio_stop: float = 0.03
    min_vix: float = 10
    max_vix: float = 25
    trend_sma_period: int = 100
    max_drawdown_pause: float = 0.04
    resume_after_days: int = 10
    risk_free_rate: float = 0.05
    iv_multiplier: float = 0.95  # IBKR 校准
    iv_skew_put: float = 1.30
    iv_skew_call: float = 0.95
    bid_ask_half_spread: float = 0.03
    bid_ask_crisis_mult: float = 3.0
    bid_ask_crisis_vix: float = 30
    slippage: float = 0.01
    crisis_vix_threshold: float = 30
    # 个股特有
    use_own_iv: bool = False  # 用自身IV还是VIX
    iv_vix_ratio: float = 1.0  # 该标的IV/VIX的历史比率


def fetch_data_for_symbol(symbol, start="2005-01-01", end="2024-12-31", iv_multiplier=0.95):
    """获取标的数据"""
    extended_start = pd.Timestamp(start) - pd.Timedelta(days=400)

    px = yf.download(symbol, start=extended_start.strftime("%Y-%m-%d"),
                     end=end, progress=False)
    vix = yf.download("^VIX", start=extended_start.strftime("%Y-%m-%d"),
                      end=end, progress=False)

    if isinstance(px.columns, pd.MultiIndex):
        px.columns = px.columns.get_level_values(0)
    if isinstance(vix.columns, pd.MultiIndex):
        vix.columns = vix.columns.get_level_values(0)

    df = pd.DataFrame(index=px.index)
    df["close"] = px["Close"]
    df["high"] = px["High"]
    df["low"] = px["Low"]
    df["vix"] = vix["Close"].reindex(px.index, method="ffill")
    df["returns"] = df["close"].pct_change()
    df["hv_20"] = df["returns"].rolling(20).std() * np.sqrt(252)
    df["iv"] = df["vix"] / 100.0 * iv_multiplier
    df["sma_100"] = df["close"].rolling(100).mean()
    df["sma_50"] = df["close"].rolling(50).mean()

    df = df.loc[start:end].copy()
    df.dropna(inplace=True)
    return df


@dataclass
class IronCondor:
    entry_date: object
    expiry_date: object
    S_entry: float
    K_short_put: float
    K_long_put: float
    K_short_call: float
    K_long_call: float
    put_premium: float
    call_premium: float
    total_premium: float
    max_profit: float
    max_loss: float
    contracts: int
    entry_iv: float


def run_backtest_multi(df, cfg: StrategyConfig):
    """通用回测引擎"""
    capital = cfg.initial_capital
    positions = []
    closed_trades = []
    equity = []
    peak_equity = capital
    paused_until = None
    last_open_date = None

    for i, (date, row) in enumerate(df.iterrows()):
        S = row["close"]
        iv_base = row["iv"]
        vix = row["vix"]
        sma_long = row["sma_100"]

        # 个股 IV 调整
        if cfg.use_own_iv:
            iv_base = iv_base * cfg.iv_vix_ratio

        # 1. Portfolio stop
        if positions:
            total_unreal = 0
            for pos in positions:
                dte_remain = (pos.expiry_date - date).days
                T = max(dte_remain, 0.5) / 365.0
                iv_p = apply_iv_skew(iv_base, "put")
                iv_c = apply_iv_skew(iv_base, "call")
                put_spread_val = spread_value(S, pos.K_short_put, pos.K_long_put, T, cfg.risk_free_rate, iv_p)
                call_spread_val = bear_call_spread_value(S, pos.K_short_call, pos.K_long_call, T, cfg.risk_free_rate, iv_c)
                current_val = (put_spread_val + call_spread_val) * 100 * pos.contracts
                entry_val = pos.total_premium * 100 * pos.contracts
                pnl = entry_val - current_val
                total_unreal += pnl

            if total_unreal <= -capital * cfg.portfolio_stop:
                for pos in positions:
                    closed_trades.append({"date": date, "pnl": total_unreal / len(positions), "reason": "portfolio_stop"})
                capital += total_unreal
                # 扣佣金
                commission = len(positions) * 8 * cfg.commission_per_leg
                capital -= commission
                positions = []
                paused_until = date + pd.Timedelta(days=cfg.resume_after_days)
                equity.append(capital)
                continue

        # 2. 管理持仓
        to_close = []
        for j, pos in enumerate(positions):
            dte_remain = (pos.expiry_date - date).days
            T = max(dte_remain, 0.5) / 365.0
            iv_p = apply_iv_skew(iv_base, "put")
            iv_c = apply_iv_skew(iv_base, "call")
            put_sv = spread_value(S, pos.K_short_put, pos.K_long_put, T, cfg.risk_free_rate, iv_p)
            call_sv = bear_call_spread_value(S, pos.K_short_call, pos.K_long_call, T, cfg.risk_free_rate, iv_c)
            current_prem = put_sv + call_sv
            pnl = (pos.total_premium - current_prem) * 100 * pos.contracts
            close_reason = None

            if pnl >= pos.max_profit * cfg.profit_target:
                close_reason = "profit_target"
            elif dte_remain <= cfg.dte_exit:
                close_reason = "dte_exit"

            if close_reason:
                friction = calc_friction_cost(vix) * 100 * pos.contracts
                commission = 8 * cfg.commission_per_leg
                net_pnl = pnl - friction - commission
                capital += net_pnl
                closed_trades.append({"date": date, "pnl": net_pnl, "reason": close_reason})
                to_close.append(j)

        for j in sorted(to_close, reverse=True):
            positions.pop(j)

        # 3. Drawdown pause
        if capital > peak_equity:
            peak_equity = capital
        drawdown = (peak_equity - capital) / peak_equity if peak_equity > 0 else 0

        if drawdown >= cfg.max_drawdown_pause and paused_until is None:
            paused_until = date + pd.Timedelta(days=cfg.resume_after_days)

        if paused_until and date >= paused_until:
            peak_equity = capital
            paused_until = None

        if paused_until:
            equity.append(capital)
            continue

        # 4. 开新仓
        if last_open_date and (date - last_open_date).days < 1:
            equity.append(capital)
            continue

        trend_ok = S > sma_long
        crisis = vix > cfg.crisis_vix_threshold

        can_open = (
            len(positions) < cfg.max_positions
            and vix >= cfg.min_vix
            and vix <= cfg.max_vix
            and trend_ok
            and not crisis
        )

        if can_open:
            # Delta 调整
            delta = cfg.short_put_delta
            if vix > cfg.delta_vix_threshold:
                delta = cfg.delta_high_vix

            iv_p = apply_iv_skew(iv_base, "put")
            iv_c = apply_iv_skew(iv_base, "call")
            T = cfg.dte_target / 365.0

            K_short_put = find_strike_by_delta(S, T, cfg.risk_free_rate, iv_p, delta, "put", 1.0)
            K_long_put = K_short_put - cfg.spread_width
            K_short_call = find_strike_by_delta(S, T, cfg.risk_free_rate, iv_c, delta, "call", 1.0)
            K_long_call = K_short_call + cfg.spread_width

            if K_short_call <= K_short_put:
                equity.append(capital)
                continue

            put_prem = spread_value(S, K_short_put, K_long_put, T, cfg.risk_free_rate, iv_p)
            call_prem = bear_call_spread_value(S, K_short_call, K_long_call, T, cfg.risk_free_rate, iv_c)
            total_prem = put_prem + call_prem

            if total_prem <= 0.02:
                equity.append(capital)
                continue

            max_loss_per = (cfg.spread_width - total_prem) * 100
            if max_loss_per <= 0 or np.isnan(max_loss_per) or capital <= 0:
                equity.append(capital)
                continue
            max_contracts = max(1, int(capital * cfg.max_risk_per_trade / max_loss_per))

            # 摩擦成本
            friction = calc_friction_cost(vix) * 100 * max_contracts
            commission = 8 * cfg.commission_per_leg
            net_premium = total_prem * 100 * max_contracts - friction - commission

            if net_premium <= 0:
                equity.append(capital)
                continue

            max_profit = net_premium
            max_loss = max_loss_per * max_contracts + friction + commission

            ic = IronCondor(
                entry_date=date,
                expiry_date=date + pd.Timedelta(days=cfg.dte_target),
                S_entry=S,
                K_short_put=K_short_put, K_long_put=K_long_put,
                K_short_call=K_short_call, K_long_call=K_long_call,
                put_premium=put_prem, call_premium=call_prem,
                total_premium=total_prem, max_profit=max_profit,
                max_loss=max_loss, contracts=max_contracts,
                entry_iv=iv_base
            )
            positions.append(ic)
            last_open_date = date

        equity.append(capital)

    # 计算指标
    eq = pd.Series(equity, index=df.index[:len(equity)])
    total_return = (capital - cfg.initial_capital) / cfg.initial_capital
    years = len(df) / 252
    annual_return = (1 + total_return) ** (1 / years) - 1 if years > 0 and total_return > -1 else -1

    # Max drawdown
    peak = eq.expanding().max()
    dd = (eq - peak) / peak
    max_dd = abs(dd.min()) * 100

    # Sharpe
    daily_ret = eq.pct_change().dropna()
    sharpe = daily_ret.mean() / daily_ret.std() * np.sqrt(252) if daily_ret.std() > 0 else 0

    # Win rate
    pnls = [t["pnl"] for t in closed_trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    win_rate = len(wins) / len(pnls) if pnls else 0

    # Score (target: annual >= 20%, maxDD <= 8%)
    annual_pct = annual_return * 100
    ret_score = min(annual_pct / 20.0, 1.5) * 50
    dd_score = min(8.0 / max(max_dd, 0.1), 1.5) * 50
    score = ret_score + dd_score

    return {
        "symbol": cfg.symbol,
        "annual_return": annual_pct,
        "max_drawdown": max_dd,
        "sharpe": sharpe,
        "total_trades": len(pnls),
        "win_rate": win_rate * 100,
        "final_equity": capital,
        "score": score,
    }


# ============================================================
# 从 IBKR 数据计算每个标的的 IV/VIX 比率
# ============================================================
def get_iv_vix_ratio(symbol):
    """从 IBKR 数据获取 IV/VIX 比率"""
    iv_file = f"ibkr_data/{symbol.lower()}_iv_history.csv"
    if not os.path.exists(iv_file):
        return 1.0

    iv_df = pd.read_csv(iv_file)
    iv_df['date'] = pd.to_datetime(iv_df['date'])
    iv_df = iv_df.set_index('date')

    # 获取同期 VIX
    vix = yf.download("^VIX", start=iv_df.index[0].strftime('%Y-%m-%d'),
                       end=iv_df.index[-1].strftime('%Y-%m-%d'), progress=False)
    if isinstance(vix.columns, pd.MultiIndex):
        vix.columns = vix.columns.get_level_values(0)
    vix.index = vix.index.tz_localize(None)

    merged = pd.DataFrame()
    merged['real_iv'] = iv_df['close']
    merged['vix'] = vix['Close']
    merged = merged.dropna()

    if len(merged) > 0:
        ratio = (merged['real_iv'] / (merged['vix'] / 100)).mean()
        return ratio
    return 1.0


if __name__ == "__main__":
    print("=" * 70)
    print("多标的 Iron Condor 策略回测 (IBKR 真实 IV 校准)")
    print("=" * 70)

    # 计算 IV/VIX 比率
    ratios = {}
    for sym in ['SPY', 'QQQ', 'AAPL', 'MSFT', 'GOOGL', 'AMZN', 'NVDA', 'META', 'TSLA']:
        r = get_iv_vix_ratio(sym)
        ratios[sym] = r
        print(f"  {sym}: IV/VIX = {r:.4f}")

    print()

    # 回测每个标的
    results = []

    # SPY 配置 (已优化)
    spy_cfg = StrategyConfig(
        symbol="SPY", iv_multiplier=0.95, iv_skew_put=1.30,
        short_put_delta=0.30, spread_width=5, max_positions=4,
        max_risk_per_trade=0.025, iv_vix_ratio=ratios.get('SPY', 0.82),
    )

    # QQQ 配置 (IV 更高，可能更好)
    qqq_cfg = StrategyConfig(
        symbol="QQQ", iv_multiplier=0.95, iv_skew_put=1.25,
        short_put_delta=0.28, spread_width=5, max_positions=4,
        max_risk_per_trade=0.025, iv_vix_ratio=ratios.get('QQQ', 1.10),
        use_own_iv=True,
    )

    # M7 个股配置 — 高IV标的用更保守的delta
    m7_configs = {}
    for sym in ['AAPL', 'MSFT', 'GOOGL', 'AMZN', 'NVDA', 'META', 'TSLA']:
        r = ratios.get(sym, 1.5)
        # 高IV标的用更低delta、更窄价差
        if r > 2.0:  # NVDA, TSLA — 极高波动
            delta, width, max_pos = 0.18, 10, 3
        elif r > 1.5:  # META, AMZN, GOOGL
            delta, width, max_pos = 0.22, 7, 3
        else:  # AAPL, MSFT
            delta, width, max_pos = 0.26, 5, 4

        m7_configs[sym] = StrategyConfig(
            symbol=sym, iv_multiplier=0.95, iv_skew_put=1.20,
            iv_skew_call=0.95, short_put_delta=delta,
            spread_width=width, max_positions=max_pos,
            max_risk_per_trade=0.02, iv_vix_ratio=r,
            use_own_iv=True,
        )

    # 运行回测
    all_configs = [spy_cfg, qqq_cfg] + list(m7_configs.values())

    for cfg in all_configs:
        print(f"\n{'='*50}")
        print(f"回测: {cfg.symbol} (delta={cfg.short_put_delta}, spread=${cfg.spread_width}, IV/VIX={cfg.iv_vix_ratio:.2f})")
        print(f"{'='*50}")

        df = fetch_data_for_symbol(cfg.symbol, iv_multiplier=cfg.iv_multiplier)
        print(f"  数据: {df.index[0].date()} ~ {df.index[-1].date()} ({len(df)}天)")

        result = run_backtest_multi(df, cfg)
        results.append(result)

        target_met = "✅" if result['annual_return'] >= 20 and result['max_drawdown'] <= 8 else "❌"
        print(f"  年化: {result['annual_return']:.2f}%")
        print(f"  回撤: -{result['max_drawdown']:.2f}%")
        print(f"  夏普: {result['sharpe']:.2f}")
        print(f"  交易: {result['total_trades']} | 胜率: {result['win_rate']:.1f}%")
        print(f"  SCORE: {result['score']:.2f} {target_met}")

    # 排行榜
    print(f"\n{'='*70}")
    print("排行榜 (按 SCORE 排序)")
    print(f"{'='*70}")
    print(f"{'标的':<8} {'年化':>8} {'回撤':>8} {'夏普':>6} {'交易':>6} {'胜率':>6} {'SCORE':>8} {'达标'}")
    print("-" * 70)

    for r in sorted(results, key=lambda x: x['score'], reverse=True):
        target = "✅" if r['annual_return'] >= 20 and r['max_drawdown'] <= 8 else "❌"
        print(f"{r['symbol']:<8} {r['annual_return']:>7.2f}% {-r['max_drawdown']:>7.2f}% {r['sharpe']:>6.2f} {r['total_trades']:>6} {r['win_rate']:>5.1f}% {r['score']:>8.2f} {target}")

    # AUTORESEARCH METRIC
    best = max(results, key=lambda x: x['score'])
    print(f"\n  === AUTORESEARCH METRIC ===")
    print(f"  BEST_SYMBOL: {best['symbol']}")
    print(f"  SCORE: {best['score']:.2f}")
    print(f"  ANNUAL_RETURN: {best['annual_return']:.2f}")
    print(f"  MAX_DRAWDOWN: {best['max_drawdown']:.2f}")
