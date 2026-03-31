#!/usr/bin/env python3
"""
策略扫描 — 使用主 backtest 引擎测试多个标的和关键参数变体
"""
import sys, os, types
import pandas as pd
import numpy as np
import yfinance as yf

sys.path.insert(0, os.path.dirname(__file__))
import config as cfg_module
from strategy import run_backtest
from dataclasses import dataclass

print = __builtins__['print'] if isinstance(__builtins__, dict) else print
import functools
orig_print = print

# ─── 数据获取 ────────────────────────────────────────────────────────
def get_data(symbol, iv_mult, start="2005-01-01", end="2024-12-31"):
    """获取回测所需数据"""
    import sys as _sys
    # Temporarily patch config
    orig_sym = cfg_module.UNDERLYING
    orig_mult = cfg_module.IV_MULTIPLIER

    ext = pd.Timestamp(start) - pd.Timedelta(days=400)
    px = yf.download(symbol, start=ext.strftime("%Y-%m-%d"), end=end, progress=False)
    vx = yf.download("^VIX", start=ext.strftime("%Y-%m-%d"), end=end, progress=False)

    for d in [px, vx]:
        if isinstance(d.columns, pd.MultiIndex):
            d.columns = d.columns.get_level_values(0)

    df = pd.DataFrame(index=px.index)
    df["close"] = px["Close"]
    df["high"] = px.get("High", px["Close"])
    df["low"] = px.get("Low", px["Close"])
    df["vix"] = vx["Close"].reindex(px.index, method="ffill")
    df["returns"] = df["close"].pct_change()
    df["hv_20"] = df["returns"].rolling(20).std() * np.sqrt(252)
    df["iv"] = df["vix"] / 100.0 * iv_mult
    df["sma_50"] = df["close"].rolling(50).mean()
    df["sma_100"] = df["close"].rolling(100).mean()
    df["sma_200"] = df["close"].rolling(200).mean()
    df["sma_20"] = df["close"].rolling(20).mean()
    df = df.loc[start:end].copy()
    df.dropna(inplace=True)

    cfg_module.UNDERLYING = orig_sym
    cfg_module.IV_MULTIPLIER = orig_mult
    return df


def patch_cfg(**kw):
    """临时修改 config 模块"""
    old = {}
    for k, v in kw.items():
        old[k] = getattr(cfg_module, k)
        setattr(cfg_module, k, v)
    return old

def restore_cfg(old):
    for k, v in old.items():
        setattr(cfg_module, k, v)


# ─── 扫描 ────────────────────────────────────────────────────────────
def scan():
    winning = []

    # ── 标的 & IV 校准 ──
    targets = {
        "SPY":  0.95,
        "QQQ":  1.11,
        "IWM":  1.22,
        "DIA":  0.76,
        "EEM":  1.15,
        "GLD":  0.90,
        "TLT":  0.85,
        "XLF":  1.05,
        "XLE":  1.10,
    }

    # ── 核心参数变体（基于已知有效配置展开）──
    # 基线: delta=0.30, spread=5, max_pos=4, dte=7, pt=0.40, max_vix=25
    variants = [
        # (label, delta, spread, max_pos, dte, pt, max_vix, risk_pct)
        ("基线",         0.30, 5, 4, 7,  0.40, 25, 0.025),
        ("低delta",      0.20, 5, 4, 7,  0.40, 25, 0.025),
        ("高delta",      0.35, 5, 4, 7,  0.40, 25, 0.025),
        ("宽价差",       0.30, 7, 4, 7,  0.40, 25, 0.025),
        ("窄价差",       0.30, 3, 4, 7,  0.40, 25, 0.025),
        ("多仓位",       0.30, 5, 5, 7,  0.40, 25, 0.025),
        ("少仓位",       0.30, 5, 3, 7,  0.40, 25, 0.025),
        ("长DTE",        0.30, 5, 4, 14, 0.40, 25, 0.025),
        ("中DTE",        0.30, 5, 4, 10, 0.40, 25, 0.025),
        ("短DTE",        0.30, 5, 4, 5,  0.40, 25, 0.025),
        ("高PT",         0.30, 5, 4, 7,  0.50, 25, 0.025),
        ("低PT",         0.30, 5, 4, 7,  0.35, 25, 0.025),
        ("宽VIX",        0.30, 5, 4, 7,  0.40, 30, 0.025),
        ("窄VIX",        0.30, 5, 4, 7,  0.40, 22, 0.025),
        ("高风险",       0.30, 5, 4, 7,  0.40, 25, 0.030),
        ("低风险",       0.30, 5, 4, 7,  0.40, 25, 0.020),
        # 组合优化
        ("组合A",        0.25, 5, 4, 7,  0.40, 25, 0.025),
        ("组合B",        0.25, 5, 4, 10, 0.40, 25, 0.025),
        ("组合C",        0.25, 7, 4, 7,  0.40, 25, 0.025),
        ("组合D",        0.30, 5, 4, 10, 0.50, 25, 0.025),
        ("组合E",        0.20, 7, 3, 14, 0.50, 22, 0.020),
        ("组合F",        0.25, 5, 5, 7,  0.40, 30, 0.025),
        ("组合G",        0.30, 7, 4, 10, 0.40, 25, 0.025),
        ("组合H",        0.25, 5, 4, 7,  0.50, 25, 0.025),
    ]

    print("=" * 70)
    print("策略扫描 — 9个标的 × 24种参数配置")
    print("目标: 年化≥20%, 最大回撤≤10%")
    print("=" * 70)
    print(f"总测试数: {len(targets) * len(variants)}")

    for sym, iv_mult in targets.items():
        print(f"\n{'─'*55}  {sym}")
        try:
            df = get_data(sym, iv_mult)
        except Exception as e:
            print(f"  数据获取失败: {e}")
            continue

        if len(df) < 500:
            print(f"  数据不足: {len(df)}行")
            continue
        print(f"  数据: {df.index[0].date()}~{df.index[-1].date()} {len(df)}天")

        for label, delta, spread, max_pos, dte, pt, max_vix, risk in variants:
            old = patch_cfg(
                SHORT_PUT_DELTA=delta, SPREAD_WIDTH=spread,
                MAX_POSITIONS=max_pos, DTE_TARGET=dte,
                DTE_MIN=max(2, dte-3), DTE_MAX=dte+3,
                PROFIT_TARGET=pt, MAX_VIX=max_vix,
                MAX_RISK_PER_TRADE=risk,
                IV_MULTIPLIER=iv_mult,
            )
            try:
                r = run_backtest(df)
                m = r.metrics
                annual = m["annual_return"] * 100
                dd = abs(m["max_drawdown"] * 100)
            except Exception as e:
                restore_cfg(old)
                continue
            restore_cfg(old)

            status = "✅" if annual >= 20 and dd <= 10 else ""

            if status:
                score = min(annual/20.0,1.5)*50 + min(10.0/max(dd,0.1),1.5)*50
                print(f"  {status} {label:<8} {sym} | 年化{annual:.1f}% DD{dd:.1f}% 夏普{m['sharpe_ratio']:.2f} ★{score:.1f}")
                winning.append({
                    "symbol": sym, "label": label, "delta": delta,
                    "spread": spread, "max_pos": max_pos, "dte": dte,
                    "pt": pt, "max_vix": max_vix, "risk": risk,
                    "annual": annual, "dd": dd,
                    "sharpe": m["sharpe_ratio"],
                    "win_rate": m["win_rate"] * 100,
                    "trades": m["total_trades"],
                    "final": m["final_equity"],
                    "score": score
                })

    return winning


def main():
    winning = scan()

    print(f"\n\n{'='*70}")
    print(f"扫描完成 | 达标策略: {len(winning)}")
    print(f"{'='*70}")

    if not winning:
        print("❌ 无达标策略")
        return

    winning.sort(key=lambda x: x["score"], reverse=True)

    # 全部达标策略
    print(f"\n所有达标策略 (年化≥20% + 回撤≤10%):")
    print(f"{'标的':<5} {'配置':<8} {'年化':>7} {'回撤':>7} {'夏普':>6} {'胜率':>7} {'交易':>6} {'★':>6}")
    print("─" * 60)
    for r in winning:
        print(f"{r['symbol']:<5} {r['label']:<8} {r['annual']:>6.1f}% {-r['dd']:>6.1f}% "
              f"{r['sharpe']:>6.2f} {r['win_rate']:>6.1f}% {r['trades']:>6} {r['score']:>6.1f}")

    # 各标的最优
    by_sym = {}
    for r in winning:
        if r["symbol"] not in by_sym or r["score"] > by_sym[r["symbol"]]["score"]:
            by_sym[r["symbol"]] = r

    print(f"\n\n{'='*70}")
    print("各标的最优策略 — 操作手册")
    print(f"{'='*70}")

    for i, r in enumerate(sorted(by_sym.values(), key=lambda x: x["score"], reverse=True), 1):
        print(f"""
{'━'*65}
第{i}优选  【{r['symbol']}】Iron Condor（铁鹰策略）
{'━'*65}
  业绩:  年化收益 {r['annual']:.2f}%  最大回撤 -{r['dd']:.2f}%  夏普 {r['sharpe']:.2f}
  统计:  胜率 {r['win_rate']:.1f}%  总交易 {r['trades']}笔  综合评分 ★{r['score']:.1f}
  增长:  $10,000 → ${r['final']:,.0f}（2005-2024，20年）

  操作参数:
  ┌─ 入场条件 ─────────────────────────────────────
  │  标的:      {r['symbol']} ETF
  │  策略:      Iron Condor（卖出牛市价差 + 卖出熊市价差）
  │  短腿Delta: {r['delta']}（VIX>22时改为0.10，更保守）
  │  价差宽度:  ${r['spread']}（两侧各${r['spread']}）
  │  到期天数:  {r['dte']}天
  │  VIX要求:  10-{r['max_vix']}（超{r['max_vix']}不开仓）
  │  趋势过滤: 价格需在SMA100之上
  ├─ 仓位管理 ─────────────────────────────────────
  │  同时持仓:  最多{r['max_pos']}个Iron Condor
  │  每笔风险:  账户资金的{r['risk']*100:.1f}%
  │  开仓频率:  每天最多1个新仓
  ├─ 退出规则 ─────────────────────────────────────
  │  盈利目标:  收到权利金的{r['pt']*100:.0f}%时平仓
  │  到期退出:  到期前1天平仓
  ├─ 风控熔断 ─────────────────────────────────────
  │  组合止损:  当日总浮亏超账户3%全部平仓
  │  回撤暂停:  回撤超4%暂停10天
  │  危机熔断:  VIX>30完全停止交易
  └────────────────────────────────────────────────""")

    # 保存
    out = os.path.join(os.path.dirname(__file__), "winning_strategies.csv")
    pd.DataFrame(winning).to_csv(out, index=False)
    print(f"\n✅ 结果已保存: {out}")


if __name__ == "__main__":
    main()
