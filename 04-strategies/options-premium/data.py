"""
数据获取模块
"""
import yfinance as yf
import pandas as pd
import numpy as np
from config import START_DATE, END_DATE, UNDERLYING, VIX_TICKER, IV_MULTIPLIER


def fetch_data():
    """获取标的和 VIX 历史数据"""
    # 多取一些前置数据用于计算指标（SMA200 需要至少 300 天前置数据）
    extended_start = pd.Timestamp(START_DATE) - pd.Timedelta(days=400)

    spy = yf.download(UNDERLYING, start=extended_start.strftime("%Y-%m-%d"),
                      end=END_DATE, progress=False)
    vix = yf.download(VIX_TICKER, start=extended_start.strftime("%Y-%m-%d"),
                      end=END_DATE, progress=False)

    # 处理 MultiIndex columns（yfinance 新版本）
    if isinstance(spy.columns, pd.MultiIndex):
        spy.columns = spy.columns.get_level_values(0)
    if isinstance(vix.columns, pd.MultiIndex):
        vix.columns = vix.columns.get_level_values(0)

    # 合并
    df = pd.DataFrame(index=spy.index)
    df["close"] = spy["Close"]
    df["high"] = spy["High"]
    df["low"] = spy["Low"]
    df["vix"] = vix["Close"].reindex(spy.index, method="ffill")

    # 计算历史波动率（20日）
    df["returns"] = df["close"].pct_change()
    df["hv_20"] = df["returns"].rolling(20).std() * np.sqrt(252)

    # 隐含波动率代理（VIX / 100 × IBKR校准系数）
    # IV_MULTIPLIER = 0.8231 来自 IBKR 5年真实数据: 真实30天ATM IV / VIX ≈ 0.82
    df["iv"] = df["vix"] / 100.0 * IV_MULTIPLIER

    # SMA
    df["sma_50"] = df["close"].rolling(50).mean()
    df["sma_200"] = df["close"].rolling(200).mean()
    df["sma_100"] = df["close"].rolling(100).mean()
    df["sma_20"] = df["close"].rolling(20).mean()

    # 截取回测区间
    df = df.loc[START_DATE:END_DATE].copy()
    df.dropna(inplace=True)

    return df


if __name__ == "__main__":
    df = fetch_data()
    print(f"数据区间: {df.index[0].date()} ~ {df.index[-1].date()}")
    print(f"交易日数: {len(df)}")
    print(f"SPY 范围: ${df['close'].min():.2f} ~ ${df['close'].max():.2f}")
    print(f"VIX 范围: {df['vix'].min():.1f} ~ {df['vix'].max():.1f}")
