"""
核心策略：系统化 Iron Condor 卖方策略
上下两侧都卖 = 双倍权利金收入
"""
import numpy as np
import pandas as pd
from dataclasses import dataclass, field
from pricing import (find_strike_by_delta, spread_value, bs_price,
                     bear_call_spread_value, bs_delta,
                     apply_iv_skew, calc_friction_cost)
import config as cfg


@dataclass
class IronCondor:
    """一个 Iron Condor 持仓"""
    entry_date: pd.Timestamp
    expiry_date: pd.Timestamp
    # Put side (Bull Put Spread)
    K_short_put: float
    K_long_put: float
    put_premium: float
    # Call side (Bear Call Spread)
    K_short_call: float
    K_long_call: float
    call_premium: float
    # Overall
    total_premium: float   # 总权利金 = put_premium + call_premium
    contracts: int
    entry_price: float
    max_loss: float        # max loss = spread_width - total_premium (per side)
    max_profit: float      # max profit = total_premium × 100 × contracts


@dataclass
class BacktestResult:
    equity_curve: pd.Series = None
    trades: list = field(default_factory=list)
    metrics: dict = field(default_factory=dict)


def _calc_ic_pnl(pos, S, iv, date, vix=15):
    """计算 Iron Condor 当前 PnL（含波动率偏斜）"""
    dte = (pos.expiry_date - date).days
    T = max(dte / 365.0, 0.001)
    r = cfg.RISK_FREE_RATE

    # 使用偏斜调整后的 IV
    iv_put = apply_iv_skew(iv, "put")
    iv_call = apply_iv_skew(iv, "call")

    # Put side value (用 put IV)
    short_put = bs_price(S, pos.K_short_put, T, r, iv_put, "put")
    long_put = bs_price(S, pos.K_long_put, T, r, iv_put, "put")
    put_cost = short_put - long_put

    # Call side value (用 call IV)
    short_call = bs_price(S, pos.K_short_call, T, r, iv_call, "call")
    long_call = bs_price(S, pos.K_long_call, T, r, iv_call, "call")
    call_cost = short_call - long_call

    total_cost = put_cost + call_cost
    pnl_per_share = pos.total_premium - total_cost
    pnl = pnl_per_share * 100 * pos.contracts
    return pnl, dte


def run_backtest(df: pd.DataFrame) -> BacktestResult:
    """运行 Iron Condor 回测"""
    capital = cfg.INITIAL_CAPITAL
    positions = []
    closed_trades = []
    equity = []
    paused_until = None
    peak_equity = capital
    last_open_date = None
    comm = getattr(cfg, 'COMMISSION_PER_LEG', 0.65)

    for date, row in df.iterrows():
        S = row["close"]
        iv = row["iv"] * cfg.IV_MULTIPLIER
        vix = row["vix"]
        sma_key = f"sma_{cfg.TREND_SMA_PERIOD}"
        sma_long = row.get(sma_key, row.get("sma_200", row.get("sma_50", S)))

        # ===== 1. 组合层面风控 =====
        if positions and cfg.PORTFOLIO_STOP < 100:
            total_unreal = sum(_calc_ic_pnl(p, S, iv, date, vix)[0] for p in positions)
            if total_unreal <= -capital * cfg.PORTFOLIO_STOP:
                for pos in positions:
                    pnl, _ = _calc_ic_pnl(pos, S, iv, date, vix)
                    pnl -= pos.contracts * 4 * comm  # 8 legs for IC close
                    # 平仓摩擦成本 (bid-ask + slippage)
                    pnl -= calc_friction_cost(vix) * 100 * pos.contracts
                    capital += pnl
                    closed_trades.append(_trade_record(pos, date, S, pnl, "portfolio_stop"))
                positions = []
                paused_until = date + pd.Timedelta(days=cfg.RESUME_AFTER_DAYS)
                equity.append(capital)
                continue

        # ===== 2. 管理持仓 =====
        to_close = []
        for j, pos in enumerate(positions):
            pnl, dte = _calc_ic_pnl(pos, S, iv, date, vix)
            close_reason = None

            if pnl >= pos.max_profit * cfg.PROFIT_TARGET:
                close_reason = "profit_target"
            elif cfg.STOP_LOSS < 100 and pnl <= -pos.max_profit * cfg.STOP_LOSS:
                close_reason = "stop_loss"
            elif dte <= cfg.DTE_EXIT:
                close_reason = "dte_exit"
            elif dte <= 0:
                # 到期结算
                put_val = max(pos.K_short_put - S, 0) - max(pos.K_long_put - S, 0)
                call_val = max(S - pos.K_short_call, 0) - max(S - pos.K_long_call, 0)
                settle = put_val + call_val
                pnl = (pos.total_premium - settle) * 100 * pos.contracts
                close_reason = "expiry"

            if close_reason:
                pnl -= pos.contracts * 4 * comm
                # 平仓摩擦成本
                if close_reason != "expiry":  # 到期结算无bid-ask
                    pnl -= calc_friction_cost(vix) * 100 * pos.contracts
                capital += pnl
                closed_trades.append(_trade_record(pos, date, S, pnl, close_reason))
                to_close.append(j)

        for j in sorted(to_close, reverse=True):
            positions.pop(j)

        # ===== 3. 回撤保护 =====
        if capital > peak_equity:
            peak_equity = capital
        drawdown = (peak_equity - capital) / peak_equity

        if paused_until and date >= paused_until:
            peak_equity = capital
            paused_until = None

        if paused_until is None and drawdown >= cfg.MAX_DRAWDOWN_PAUSE:
            paused_until = date + pd.Timedelta(days=cfg.RESUME_AFTER_DAYS)

        if paused_until and date < paused_until:
            equity.append(capital)
            continue

        # ===== 4. 开新仓 =====
        if last_open_date and (date - last_open_date).days < 1:
            can_open_freq = False
        else:
            can_open_freq = True

        trend_ok = True
        if cfg.REQUIRE_ABOVE_SMA and S <= sma_long:
            trend_ok = False

        # 危机模式：VIX 极高时完全停止交易
        crisis_vix = getattr(cfg, 'CRISIS_VIX_THRESHOLD', 999)

        can_open = (
            can_open_freq
            and len(positions) < cfg.MAX_POSITIONS
            and vix >= cfg.MIN_VIX
            and vix <= cfg.MAX_VIX
            and vix < crisis_vix  # 危机熔断
            and trend_ok
            and date.weekday() in [0, 1, 2, 3, 4]  # 全周开仓
        )

        if can_open:
            T = cfg.DTE_TARGET / 365.0
            expiry = date + pd.Timedelta(days=cfg.DTE_TARGET)

            delta = cfg.SHORT_PUT_DELTA
            if cfg.DELTA_VIX_ADJUST and vix > cfg.DELTA_VIX_THRESHOLD:
                delta = cfg.DELTA_HIGH_VIX

            # 使用偏斜调整后的 IV 来定价
            iv_put = apply_iv_skew(iv, "put")
            iv_call = apply_iv_skew(iv, "call")

            # Put side (用 put 偏斜 IV)
            K_short_put = find_strike_by_delta(
                S, T, cfg.RISK_FREE_RATE, iv_put,
                delta, "put", strike_step=1.0
            )
            K_long_put = K_short_put - cfg.SPREAD_WIDTH
            put_prem = spread_value(S, K_short_put, K_long_put, T, cfg.RISK_FREE_RATE, iv_put)

            # Call side (用 call 偏斜 IV)
            K_short_call = find_strike_by_delta(
                S, T, cfg.RISK_FREE_RATE, iv_call,
                delta, "call", strike_step=1.0
            )
            K_long_call = K_short_call + cfg.SPREAD_WIDTH
            call_prem = bear_call_spread_value(
                S, K_short_call, K_long_call, T, cfg.RISK_FREE_RATE, iv_call
            )

            total_prem = put_prem + call_prem

            # 扣除开仓摩擦成本 (bid-ask + slippage)
            friction = calc_friction_cost(vix)
            net_prem = total_prem - friction  # 实际到手权利金

            if net_prem <= 0.05:
                equity.append(capital)
                continue

            # 仓位 — 基于单侧最大亏损
            max_loss_one_side = (cfg.SPREAD_WIDTH - min(put_prem, call_prem)) * 100
            risk_budget = capital * cfg.MAX_RISK_PER_TRADE
            contracts = max(1, int(risk_budget / max_loss_one_side))

            # 开仓佣金 (8 legs for IC)
            open_comm = contracts * 4 * comm
            capital -= open_comm
            # 开仓摩擦成本
            capital -= friction * 100 * contracts

            positions.append(IronCondor(
                entry_date=date,
                expiry_date=expiry,
                K_short_put=K_short_put,
                K_long_put=K_long_put,
                put_premium=put_prem,
                K_short_call=K_short_call,
                K_long_call=K_long_call,
                call_premium=call_prem,
                total_premium=total_prem,
                contracts=contracts,
                entry_price=S,
                max_loss=max_loss_one_side * contracts,
                max_profit=total_prem * 100 * contracts,
            ))
            last_open_date = date

        equity.append(capital)

    equity_series = pd.Series(equity, index=df.index[:len(equity)])
    return BacktestResult(
        equity_curve=equity_series,
        trades=closed_trades,
        metrics=calculate_metrics(equity_series, closed_trades),
    )


def _trade_record(pos, date, S, pnl, reason):
    return {
        "entry_date": pos.entry_date,
        "exit_date": date,
        "K_short_put": pos.K_short_put,
        "K_long_put": pos.K_long_put,
        "K_short_call": pos.K_short_call,
        "K_long_call": pos.K_long_call,
        "premium": pos.total_premium,
        "contracts": pos.contracts,
        "pnl": pnl,
        "reason": reason,
        "entry_price": pos.entry_price,
        "exit_price": S,
        # Backward compat
        "K_short": pos.K_short_put,
        "K_long": pos.K_long_put,
    }


def calculate_metrics(equity: pd.Series, trades: list) -> dict:
    if len(equity) < 2:
        return {}

    total_return = (equity.iloc[-1] / equity.iloc[0]) - 1
    years = (equity.index[-1] - equity.index[0]).days / 365.25
    annual_return = (1 + total_return) ** (1 / years) - 1 if years > 0 else 0

    peak = equity.cummax()
    drawdown = (equity - peak) / peak
    max_drawdown = drawdown.min()

    daily_returns = equity.pct_change().dropna()
    sharpe = (daily_returns.mean() / daily_returns.std() * np.sqrt(252)
              if daily_returns.std() > 0 else 0)

    if trades:
        wins = [t for t in trades if t["pnl"] > 0]
        losses = [t for t in trades if t["pnl"] <= 0]
        win_rate = len(wins) / len(trades)
        avg_win = np.mean([t["pnl"] for t in wins]) if wins else 0
        avg_loss = np.mean([t["pnl"] for t in losses]) if losses else 0
        profit_factor = (
            abs(sum(t["pnl"] for t in wins) / sum(t["pnl"] for t in losses))
            if losses and sum(t["pnl"] for t in losses) != 0 else float("inf")
        )
    else:
        win_rate = avg_win = avg_loss = profit_factor = 0

    return {
        "total_return": total_return,
        "annual_return": annual_return,
        "max_drawdown": max_drawdown,
        "sharpe_ratio": sharpe,
        "total_trades": len(trades),
        "win_rate": win_rate,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "profit_factor": profit_factor,
        "final_equity": equity.iloc[-1],
        "years": years,
    }
