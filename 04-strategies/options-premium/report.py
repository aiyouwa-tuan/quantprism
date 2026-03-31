#!/usr/bin/env python3
"""
生成策略报告和资金曲线图
"""
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import numpy as np
import pandas as pd
from data import fetch_data
from strategy import run_backtest
import config as cfg

def generate_report():
    df = fetch_data()
    result = run_backtest(df)
    m = result.metrics
    eq = result.equity_curve

    # === 资金曲线图 ===
    fig, axes = plt.subplots(3, 1, figsize=(14, 12), gridspec_kw={"height_ratios": [3, 1, 1]})
    fig.suptitle("Iron Condor Premium Strategy — Backtest Report", fontsize=16, fontweight="bold")

    # 1. 资金曲线
    ax1 = axes[0]
    ax1.plot(eq.index, eq.values, color="#2196F3", linewidth=1.5, label="Strategy Equity")
    ax1.fill_between(eq.index, eq.iloc[0], eq.values, alpha=0.1, color="#2196F3")
    ax1.axhline(y=eq.iloc[0], color="gray", linestyle="--", alpha=0.5, label="Initial Capital")
    ax1.set_ylabel("Equity ($)")
    ax1.set_title(f"Equity Curve  |  ${eq.iloc[0]:,.0f} → ${eq.iloc[-1]:,.0f}  |  "
                  f"Annual: {m['annual_return']*100:.1f}%  |  MaxDD: {m['max_drawdown']*100:.1f}%")
    ax1.legend(loc="upper left")
    ax1.grid(True, alpha=0.3)
    ax1.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    ax1.xaxis.set_major_locator(mdates.MonthLocator(interval=6))

    # 2. 回撤曲线
    ax2 = axes[1]
    peak = eq.cummax()
    dd = (eq - peak) / peak * 100
    ax2.fill_between(dd.index, 0, dd.values, color="#F44336", alpha=0.4)
    ax2.axhline(y=-5, color="red", linestyle="--", alpha=0.7, label="5% DD Limit")
    ax2.set_ylabel("Drawdown (%)")
    ax2.set_title("Drawdown")
    ax2.legend(loc="lower left")
    ax2.grid(True, alpha=0.3)
    ax2.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    ax2.xaxis.set_major_locator(mdates.MonthLocator(interval=6))

    # 3. 每笔交易 PnL
    ax3 = axes[2]
    if result.trades:
        dates = [t["exit_date"] for t in result.trades]
        pnls = [t["pnl"] for t in result.trades]
        colors = ["#4CAF50" if p > 0 else "#F44336" for p in pnls]
        ax3.bar(dates, pnls, color=colors, alpha=0.6, width=2)
        ax3.axhline(y=0, color="gray", linestyle="-", alpha=0.5)
    ax3.set_ylabel("Trade PnL ($)")
    ax3.set_title(f"Trade PnL  |  {m['total_trades']} trades  |  "
                  f"Win Rate: {m['win_rate']*100:.1f}%  |  "
                  f"Profit Factor: {m['profit_factor']:.2f}")
    ax3.grid(True, alpha=0.3)
    ax3.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    ax3.xaxis.set_major_locator(mdates.MonthLocator(interval=6))

    plt.tight_layout()
    report_path = os.path.join(os.path.dirname(__file__), "backtest_report.png")
    plt.savefig(report_path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"\n报告已保存: {report_path}")

    # === 月度收益热力图数据 ===
    monthly = eq.resample("ME").last().pct_change().dropna()
    print("\n=== 月度收益概览 ===")
    for year in sorted(monthly.index.year.unique()):
        year_data = monthly[monthly.index.year == year]
        total = (1 + year_data).prod() - 1
        months_str = " ".join(f"{r*100:+5.1f}%" for r in year_data.values)
        print(f"  {year}: {months_str}  | 年度: {total*100:+.1f}%")

    # === 关键指标汇总 ===
    print("\n" + "=" * 60)
    print("策略最终配置和绩效汇总")
    print("=" * 60)
    print(f"""
策略名称:       Iron Condor Weekly Premium Harvester
标的:           SPY (S&P 500 ETF)
策略类型:       系统化卖方策略（Iron Condor）

--- 核心参数 ---
  卖出 Delta:    0.16 (标准) / 0.05 (高波动)
  价差宽度:      $1 (超窄定义风险)
  到期天数:      7 天 (周度期权)
  最大持仓:      3 个 Iron Condor
  组合止损:      1.8% 未实现亏损
  回撤暂停:      2% 回撤 → 暂停 10 天
  趋势过滤:      SPY > SMA100
  波动率过滤:    VIX 10-23
  止盈:          权利金的 40%
  佣金:          $0 (零佣金平台)

--- 绩效指标 ---
  年化收益率:    {m['annual_return']*100:.2f}%
  最大回撤:      {m['max_drawdown']*100:.2f}%
  夏普比率:      {m['sharpe_ratio']:.2f}
  总交易数:      {m['total_trades']}
  胜率:          {m['win_rate']*100:.1f}%
  平均盈利:      ${m['avg_win']:.2f}
  平均亏损:      ${m['avg_loss']:.2f}
  盈亏比:        {m['profit_factor']:.2f}
  初始资金:      ${cfg.INITIAL_CAPITAL:,.2f}
  最终资金:      ${m['final_equity']:,.2f}
  回测年数:      {m['years']:.1f}
""")

    return m


if __name__ == "__main__":
    generate_report()
