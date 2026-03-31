#!/usr/bin/env python3
"""
回测主入口 — 输出关键指标用于 autoresearch 验证
"""
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from data import fetch_data
from strategy import run_backtest
import config as cfg


def main():
    print("=" * 60)
    print("美股期权卖方策略回测")
    print("=" * 60)

    # 获取数据
    print("\n[1] 获取数据...")
    df = fetch_data()
    print(f"    数据区间: {df.index[0].date()} ~ {df.index[-1].date()}")
    print(f"    交易日数: {len(df)}")

    # 运行回测
    print("\n[2] 运行回测...")
    result = run_backtest(df)
    m = result.metrics

    # 输出结果
    print("\n" + "=" * 60)
    print("回测结果")
    print("=" * 60)
    print(f"  初始资金:     ${cfg.INITIAL_CAPITAL:,.2f}")
    print(f"  最终资金:     ${m['final_equity']:,.2f}")
    print(f"  总收益率:     {m['total_return']*100:.2f}%")
    print(f"  年化收益率:   {m['annual_return']*100:.2f}%")
    print(f"  最大回撤:     {m['max_drawdown']*100:.2f}%")
    print(f"  夏普比率:     {m['sharpe_ratio']:.2f}")
    print(f"  总交易数:     {m['total_trades']}")
    print(f"  胜率:         {m['win_rate']*100:.1f}%")
    print(f"  平均盈利:     ${m['avg_win']:.2f}")
    print(f"  平均亏损:     ${m['avg_loss']:.2f}")
    print(f"  盈亏比:       {m['profit_factor']:.2f}")
    print(f"  回测年数:     {m['years']:.1f}")

    # === METRIC OUTPUT（autoresearch 用）===
    # 综合得分：年化收益贡献 + 回撤惩罚
    annual_ret = m["annual_return"] * 100
    max_dd = abs(m["max_drawdown"] * 100)

    # 目标：年化≥20%，回撤≤10%
    ret_score = min(annual_ret / 20.0, 1.5) * 50   # 年化20%得50分，封顶75
    dd_score = min(10.0 / max(max_dd, 0.1), 1.5) * 50  # 回撤10%得50分，封顶75
    score = ret_score + dd_score

    print(f"\n  === AUTORESEARCH METRIC ===")
    print(f"  SCORE: {score:.2f}")
    print(f"  ANNUAL_RETURN: {annual_ret:.2f}")
    print(f"  MAX_DRAWDOWN: {max_dd:.2f}")

    # 交易明细
    if result.trades:
        print(f"\n  --- 最近 10 笔交易 ---")
        for t in result.trades[-10:]:
            if "K_short_call" in t:
                print(f"    {t['entry_date'].date()} -> {t['exit_date'].date()} | "
                      f"Put={t['K_short_put']}/{t['K_long_put']} "
                      f"Call={t['K_short_call']}/{t['K_long_call']} | "
                      f"PnL=${t['pnl']:.2f} | {t['reason']}")
            else:
                print(f"    {t['entry_date'].date()} -> {t['exit_date'].date()} | "
                      f"K={t['K_short']}/{t['K_long']} | "
                      f"PnL=${t['pnl']:.2f} | {t['reason']}")

    return score, m


if __name__ == "__main__":
    score, metrics = main()
    # 退出码：满足约束返回0，否则返回1
    if metrics["annual_return"] >= 0.20 and metrics["max_drawdown"] >= -0.10:
        sys.exit(0)
    else:
        sys.exit(1)
