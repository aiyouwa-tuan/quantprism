"""
IBKR TWS 真实数据获取模块
通过 ib_insync 连接 TWS，获取：
1. SPY 历史隐含波动率（最多 5 年日线）
2. SPY 历史波动率
3. 当前 SPY 期权链快照（用于校准 BS 模型）
"""

import sys
import time
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from ib_insync import IB, Stock, Option, util

# ============================================================
# 1. 连接测试
# ============================================================
def connect_tws(port=7496, client_id=3):
    """连接 TWS"""
    ib = IB()
    try:
        ib.connect('127.0.0.1', port, clientId=client_id, readonly=True)
        print(f"✅ 成功连接 TWS (端口 {port})")
        print(f"   服务器版本: {ib.client.serverVersion()}")
        return ib
    except Exception as e:
        if ib.isConnected():
            print(f"⚠️ 连接已建立 (警告: {e})")
            return ib
        print(f"❌ 连接失败: {e}")
        return None


# ============================================================
# 2. 获取 SPY 历史隐含波动率（标的层面）
# ============================================================
def fetch_spy_iv_history(ib, duration="5 Y", bar_size="1 day"):
    """
    获取 SPY 的 OPTION_IMPLIED_VOLATILITY 历史数据
    这是 IBKR 根据真实期权链计算的 30天 ATM IV
    比 VIX/100 更精确
    """
    print("\n[1] 获取 SPY 历史隐含波动率...")
    spy = Stock('SPY', 'SMART', 'USD')
    ib.qualifyContracts(spy)

    bars = ib.reqHistoricalData(
        spy,
        endDateTime='',
        durationStr=duration,
        barSizeSetting=bar_size,
        whatToShow='OPTION_IMPLIED_VOLATILITY',
        useRTH=True,
        formatDate=1
    )

    if not bars:
        print("   ⚠️ 无 IV 数据返回，尝试更短周期...")
        bars = ib.reqHistoricalData(
            spy, endDateTime='', durationStr="2 Y",
            barSizeSetting=bar_size,
            whatToShow='OPTION_IMPLIED_VOLATILITY',
            useRTH=True, formatDate=1
        )

    if bars:
        df = util.df(bars)
        df['date'] = pd.to_datetime(df['date'])
        df = df.set_index('date')
        # close 列 = 当天收盘时的隐含波动率
        print(f"   ✅ 获取到 {len(df)} 个交易日的 IV 数据")
        print(f"   日期范围: {df.index[0].date()} ~ {df.index[-1].date()}")
        print(f"   IV 范围: {df['close'].min():.4f} ~ {df['close'].max():.4f}")
        print(f"   IV 均值: {df['close'].mean():.4f}")
        return df
    else:
        print("   ❌ 无法获取 IV 数据")
        return None


# ============================================================
# 3. 获取 SPY 历史波动率
# ============================================================
def fetch_spy_hv_history(ib, duration="5 Y", bar_size="1 day"):
    """获取 SPY 的 HISTORICAL_VOLATILITY"""
    print("\n[2] 获取 SPY 历史波动率...")
    spy = Stock('SPY', 'SMART', 'USD')
    ib.qualifyContracts(spy)

    bars = ib.reqHistoricalData(
        spy, endDateTime='', durationStr=duration,
        barSizeSetting=bar_size,
        whatToShow='HISTORICAL_VOLATILITY',
        useRTH=True, formatDate=1
    )

    if bars:
        df = util.df(bars)
        df['date'] = pd.to_datetime(df['date'])
        df = df.set_index('date')
        print(f"   ✅ 获取到 {len(df)} 个交易日的 HV 数据")
        print(f"   HV 范围: {df['close'].min():.4f} ~ {df['close'].max():.4f}")
        return df
    else:
        print("   ❌ 无法获取 HV 数据")
        return None


# ============================================================
# 4. 获取 SPY 价格历史
# ============================================================
def fetch_spy_price_history(ib, duration="5 Y", bar_size="1 day"):
    """获取 SPY 日线价格"""
    print("\n[3] 获取 SPY 价格历史...")
    spy = Stock('SPY', 'SMART', 'USD')
    ib.qualifyContracts(spy)

    bars = ib.reqHistoricalData(
        spy, endDateTime='', durationStr=duration,
        barSizeSetting=bar_size,
        whatToShow='TRADES',
        useRTH=True, formatDate=1
    )

    if bars:
        df = util.df(bars)
        df['date'] = pd.to_datetime(df['date'])
        df = df.set_index('date')
        print(f"   ✅ 获取到 {len(df)} 个交易日的价格数据")
        print(f"   价格范围: ${df['close'].min():.2f} ~ ${df['close'].max():.2f}")
        return df
    else:
        print("   ❌ 无法获取价格数据")
        return None


# ============================================================
# 5. 获取当前 SPY 期权链快照（校准用）
# ============================================================
def fetch_option_chain_snapshot(ib, num_strikes=10):
    """
    获取 SPY 当前最近到期的期权链
    用于校准 BS 模型 vs 真实市场价格
    """
    print("\n[4] 获取 SPY 期权链快照...")
    spy = Stock('SPY', 'SMART', 'USD')
    ib.qualifyContracts(spy)

    # 获取 SPY 当前价格
    [ticker] = ib.reqTickers(spy)
    spot = ticker.marketPrice()
    if np.isnan(spot):
        spot = ticker.close
    print(f"   SPY 当前价格: ${spot:.2f}")

    # 获取期权链信息
    chains = ib.reqSecDefOptParams(spy.symbol, '', spy.secType, spy.conId)
    if not chains:
        print("   ❌ 无法获取期权链参数")
        return None, spot

    # 选择 SMART 交易所的链
    chain = None
    for c in chains:
        if c.exchange == 'SMART':
            chain = c
            break
    if chain is None:
        chain = chains[0]

    # 选择最近的到期日（7-14天内）
    today = datetime.now().date()
    expirations = sorted(chain.expirations)
    target_exp = None
    for exp in expirations:
        exp_date = datetime.strptime(exp, '%Y%m%d').date()
        dte = (exp_date - today).days
        if 5 <= dte <= 14:
            target_exp = exp
            break
    if target_exp is None and expirations:
        target_exp = expirations[0]

    print(f"   到期日: {target_exp} (DTE={( datetime.strptime(target_exp, '%Y%m%d').date() - today).days})")

    # 选择 ATM 附近的行权价
    strikes = sorted(chain.strikes)
    atm_idx = min(range(len(strikes)), key=lambda i: abs(strikes[i] - spot))
    selected_strikes = strikes[max(0, atm_idx - num_strikes):atm_idx + num_strikes + 1]

    print(f"   获取 {len(selected_strikes)} 个行权价的期权报价...")

    # 构建期权合约并获取报价
    results = []
    contracts = []
    for strike in selected_strikes:
        for right in ['P', 'C']:
            opt = Option('SPY', target_exp, strike, right, 'SMART')
            contracts.append(opt)

    ib.qualifyContracts(*contracts)
    tickers = ib.reqTickers(*contracts)
    ib.sleep(3)  # 等待数据到达

    for ticker in tickers:
        c = ticker.contract
        bid = ticker.bid if not np.isnan(ticker.bid) else 0
        ask = ticker.ask if not np.isnan(ticker.ask) else 0
        last = ticker.last if not np.isnan(ticker.last) else 0
        mid = (bid + ask) / 2 if bid > 0 and ask > 0 else last

        # 获取 Greeks
        greeks = ticker.modelGreeks or ticker.lastGreeks
        delta = iv = gamma = theta = None
        if greeks:
            delta = greeks.delta
            iv = greeks.impliedVol
            gamma = greeks.gamma
            theta = greeks.theta

        results.append({
            'expiry': c.lastTradeDateOrContractMonth,
            'strike': c.strike,
            'right': c.right,
            'bid': bid,
            'ask': ask,
            'mid': mid,
            'last': last,
            'iv': iv,
            'delta': delta,
            'gamma': gamma,
            'theta': theta,
            'bid_ask_spread': ask - bid if bid > 0 and ask > 0 else None
        })

    df = pd.DataFrame(results)
    if len(df) > 0:
        puts = df[df['right'] == 'P']
        calls = df[df['right'] == 'C']
        print(f"   ✅ 获取到 {len(puts)} 个 Put + {len(calls)} 个 Call 报价")

        # 显示 bid-ask 统计
        valid_spreads = df['bid_ask_spread'].dropna()
        if len(valid_spreads) > 0:
            print(f"   Bid-Ask 价差: 均值=${valid_spreads.mean():.3f}, "
                  f"中位数=${valid_spreads.median():.3f}, "
                  f"最大=${valid_spreads.max():.3f}")
    return df, spot


# ============================================================
# 主程序
# ============================================================
if __name__ == "__main__":
    print("=" * 60)
    print("IBKR 真实数据获取")
    print("=" * 60)

    # 连接
    ib = connect_tws()
    if ib is None:
        sys.exit(1)

    try:
        # 获取数据
        iv_df = fetch_spy_iv_history(ib)
        time.sleep(2)  # 避免 pacing violation

        hv_df = fetch_spy_hv_history(ib)
        time.sleep(2)

        price_df = fetch_spy_price_history(ib)
        time.sleep(2)

        chain_df, spot = fetch_option_chain_snapshot(ib)

        # 保存数据
        save_dir = "/Volumes/MaiTuan2T/Quant/04-strategies/options-premium/ibkr_data"
        import os
        os.makedirs(save_dir, exist_ok=True)

        if iv_df is not None:
            iv_df.to_csv(f"{save_dir}/spy_iv_history.csv")
            print(f"\n💾 IV 数据已保存: {save_dir}/spy_iv_history.csv")

        if hv_df is not None:
            hv_df.to_csv(f"{save_dir}/spy_hv_history.csv")
            print(f"💾 HV 数据已保存: {save_dir}/spy_hv_history.csv")

        if price_df is not None:
            price_df.to_csv(f"{save_dir}/spy_price_history.csv")
            print(f"💾 价格数据已保存: {save_dir}/spy_price_history.csv")

        if chain_df is not None:
            chain_df.to_csv(f"{save_dir}/spy_option_chain.csv", index=False)
            print(f"💾 期权链已保存: {save_dir}/spy_option_chain.csv")

        # ============================================================
        # 快速分析: 真实 IV vs VIX
        # ============================================================
        if iv_df is not None and price_df is not None:
            print("\n" + "=" * 60)
            print("真实 IV vs VIX 对比分析")
            print("=" * 60)

            # 合并数据
            merged = price_df[['close']].copy()
            merged.columns = ['spy_price']
            merged['real_iv'] = iv_df['close']
            merged = merged.dropna()

            # 尝试获取 VIX 数据来对比
            try:
                import yfinance as yf
                vix = yf.download("^VIX", start=merged.index[0].strftime('%Y-%m-%d'),
                                  end=merged.index[-1].strftime('%Y-%m-%d'))
                if hasattr(vix.columns, 'get_level_values'):
                    vix.columns = vix.columns.get_level_values(0)
                vix.index = vix.index.tz_localize(None)
                merged['vix'] = vix['Close']
                merged['vix_as_iv'] = merged['vix'] / 100
                merged = merged.dropna()

                # 计算差异
                diff = merged['real_iv'] - merged['vix_as_iv']
                ratio = merged['real_iv'] / merged['vix_as_iv']

                print(f"\n  对比区间: {merged.index[0].date()} ~ {merged.index[-1].date()}")
                print(f"  数据点数: {len(merged)}")
                print(f"\n  真实 IV 均值:    {merged['real_iv'].mean():.4f}")
                print(f"  VIX/100 均值:    {merged['vix_as_iv'].mean():.4f}")
                print(f"  差值 (IV-VIX):   {diff.mean():.4f} (±{diff.std():.4f})")
                print(f"  比率 (IV/VIX):   {ratio.mean():.4f} (±{ratio.std():.4f})")
                print(f"\n  📊 校准建议:")
                print(f"     IV_MULTIPLIER = {ratio.mean():.4f}")
                print(f"     (将 VIX/100 × {ratio.mean():.4f} 作为更准确的 IV 估计)")
            except Exception as e:
                print(f"  VIX 对比跳过: {e}")

        # 期权链分析
        if chain_df is not None and spot:
            print("\n" + "=" * 60)
            print("真实期权链 vs BS 模型对比")
            print("=" * 60)

            from pricing import bs_price, bs_delta, apply_iv_skew
            import config as cfg

            valid = chain_df[(chain_df['mid'] > 0) & (chain_df['iv'].notna())].copy()
            if len(valid) > 0:
                # 用真实 IV 计算 BS 价格
                dte = (datetime.strptime(valid.iloc[0]['expiry'], '%Y%m%d').date() -
                       datetime.now().date()).days
                T = max(dte, 1) / 365.0
                r = cfg.RISK_FREE_RATE

                for idx, row in valid.iterrows():
                    bs_p = bs_price(spot, row['strike'], T, r, row['iv'],
                                    "put" if row['right'] == 'P' else "call")
                    valid.loc[idx, 'bs_price'] = bs_p
                    valid.loc[idx, 'bs_error'] = bs_p - row['mid']
                    valid.loc[idx, 'bs_error_pct'] = (bs_p - row['mid']) / row['mid'] * 100 if row['mid'] > 0.01 else None

                # 统计
                puts = valid[valid['right'] == 'P']
                calls = valid[valid['right'] == 'C']

                for label, subset in [("Put", puts), ("Call", calls)]:
                    errs = subset['bs_error_pct'].dropna()
                    if len(errs) > 0:
                        print(f"\n  {label} ({len(errs)} 个有效报价):")
                        print(f"    BS 误差均值:  {errs.mean():.2f}%")
                        print(f"    BS 误差中位:  {errs.median():.2f}%")
                        print(f"    BS 误差标准差: {errs.std():.2f}%")

                # Bid-Ask 分析
                spreads = valid['bid_ask_spread'].dropna()
                if len(spreads) > 0:
                    print(f"\n  Bid-Ask 价差统计:")
                    print(f"    均值:   ${spreads.mean():.3f}/股")
                    print(f"    中位数: ${spreads.median():.3f}/股")
                    print(f"    最大:   ${spreads.max():.3f}/股")
                    print(f"\n  📊 当前回测 BID_ASK_HALF_SPREAD = ${cfg.BID_ASK_HALF_SPREAD}")
                    real_half = spreads.median() / 2
                    print(f"     真实半价差 = ${real_half:.3f}")
                    if real_half > cfg.BID_ASK_HALF_SPREAD:
                        print(f"     ⚠️ 回测偏乐观! 建议调整到 ${real_half:.3f}")
                    else:
                        print(f"     ✅ 回测已包含足够摩擦")

                # IV Skew 分析
                otm_puts = puts[(puts['delta'].notna()) & (puts['delta'].abs() < 0.25) & (puts['delta'].abs() > 0.10)]
                atm_opts = valid[(valid['delta'].notna()) & (valid['delta'].abs() > 0.40) & (valid['delta'].abs() < 0.60)]

                if len(otm_puts) > 0 and len(atm_opts) > 0:
                    otm_put_iv = otm_puts['iv'].mean()
                    atm_iv = atm_opts['iv'].mean()
                    real_skew = otm_put_iv / atm_iv
                    print(f"\n  IV Skew 分析:")
                    print(f"    ATM IV:      {atm_iv:.4f}")
                    print(f"    OTM Put IV:  {otm_put_iv:.4f}")
                    print(f"    真实偏斜:     {real_skew:.4f}")
                    print(f"    回测偏斜:     {cfg.IV_SKEW_PUT}")
                    if abs(real_skew - cfg.IV_SKEW_PUT) > 0.05:
                        print(f"    ⚠️ 偏差较大! 建议调整 IV_SKEW_PUT = {real_skew:.2f}")
                    else:
                        print(f"    ✅ 偏斜设置合理")

        print("\n" + "=" * 60)
        print("数据获取完成!")
        print("=" * 60)

    except Exception as e:
        print(f"\n❌ 错误: {e}")
        import traceback
        traceback.print_exc()
    finally:
        ib.disconnect()
        print("\n已断开 TWS 连接")
