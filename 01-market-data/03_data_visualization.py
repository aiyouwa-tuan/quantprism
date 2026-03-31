"""
==============================================
数据可视化 - K 线图与行情图表
==============================================

学习目标：
- matplotlib 基础画图
- mplfinance 画专业 K 线图
- 画收益率曲线、成交量等图表

前置要求：
    pip install matplotlib mplfinance yfinance pandas

运行方式：
    python 03_data_visualization.py

说明：
- 运行后会弹出图表窗口
- 关闭窗口后程序继续执行
- 图片也会保存到当前目录
"""

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib
import yfinance as yf

# 设置中文字体（macOS）
matplotlib.rcParams['font.sans-serif'] = ['Arial Unicode MS', 'PingFang SC', 'Heiti TC']
matplotlib.rcParams['axes.unicode_minus'] = False  # 负号显示

# ============================================
# 1. 获取数据
# ============================================

print("正在下载数据...")
df = yf.download("AAPL", period="6mo")
print(f"获取到 {len(df)} 天的 AAPL 数据")
print()

# ============================================
# 2. 基础折线图 - 收盘价
# ============================================

print("=== 图1: 收盘价折线图 ===")

fig, ax = plt.subplots(figsize=(12, 6))
ax.plot(df.index, df["Close"], color="steelblue", linewidth=1.5)
ax.set_title("AAPL 收盘价走势", fontsize=16)
ax.set_xlabel("日期")
ax.set_ylabel("价格 ($)")
ax.grid(True, alpha=0.3)
plt.tight_layout()
plt.savefig("01_close_price.png", dpi=100)
print("已保存: 01_close_price.png")
plt.close()

# ============================================
# 3. 收盘价 + 均线
# ============================================

print("=== 图2: 收盘价 + 均线 ===")

df["MA20"] = df["Close"].rolling(20).mean()
df["MA50"] = df["Close"].rolling(50).mean()

fig, ax = plt.subplots(figsize=(12, 6))
ax.plot(df.index, df["Close"], label="收盘价", color="steelblue", linewidth=1.5)
ax.plot(df.index, df["MA20"], label="MA20", color="orange", linewidth=1, linestyle="--")
ax.plot(df.index, df["MA50"], label="MA50", color="red", linewidth=1, linestyle="--")
ax.set_title("AAPL 收盘价 + 均线", fontsize=16)
ax.set_xlabel("日期")
ax.set_ylabel("价格 ($)")
ax.legend()
ax.grid(True, alpha=0.3)
plt.tight_layout()
plt.savefig("02_price_with_ma.png", dpi=100)
print("已保存: 02_price_with_ma.png")
plt.close()

# ============================================
# 4. 多子图：价格 + 成交量
# ============================================

print("=== 图3: 价格 + 成交量 双图 ===")

fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 8), gridspec_kw={"height_ratios": [3, 1]})

# 上图：价格
ax1.plot(df.index, df["Close"], color="steelblue", linewidth=1.5)
ax1.set_title("AAPL 价格与成交量", fontsize=16)
ax1.set_ylabel("价格 ($)")
ax1.grid(True, alpha=0.3)

# 下图：成交量
colors = ["green" if df["Close"].iloc[i] >= df["Close"].iloc[max(0, i-1)]
          else "red" for i in range(len(df))]
ax2.bar(df.index, df["Volume"], color=colors, alpha=0.7, width=1)
ax2.set_ylabel("成交量")
ax2.grid(True, alpha=0.3)

plt.tight_layout()
plt.savefig("03_price_volume.png", dpi=100)
print("已保存: 03_price_volume.png")
plt.close()

# ============================================
# 5. 每日收益率分布图
# ============================================

print("=== 图4: 收益率分布 ===")

daily_returns = df["Close"].pct_change().dropna() * 100

fig, ax = plt.subplots(figsize=(10, 6))
ax.hist(daily_returns, bins=50, color="steelblue", edgecolor="white", alpha=0.8)
ax.axvline(x=0, color="red", linestyle="--", linewidth=1)
ax.axvline(x=daily_returns.mean(), color="orange", linestyle="--", linewidth=1,
           label=f"均值: {daily_returns.mean():.2f}%")
ax.set_title("AAPL 每日收益率分布", fontsize=16)
ax.set_xlabel("日收益率 (%)")
ax.set_ylabel("频次")
ax.legend()
ax.grid(True, alpha=0.3)
plt.tight_layout()
plt.savefig("04_return_distribution.png", dpi=100)
print("已保存: 04_return_distribution.png")
plt.close()

# ============================================
# 6. 累计收益率曲线
# ============================================

print("=== 图5: 累计收益率 ===")

cum_return = (1 + df["Close"].pct_change()).cumprod() - 1

fig, ax = plt.subplots(figsize=(12, 6))
ax.plot(df.index, cum_return * 100, color="steelblue", linewidth=1.5)
ax.fill_between(df.index, cum_return * 100, 0, alpha=0.1, color="steelblue")
ax.axhline(y=0, color="gray", linestyle="-", linewidth=0.5)
ax.set_title("AAPL 累计收益率", fontsize=16)
ax.set_xlabel("日期")
ax.set_ylabel("累计收益率 (%)")
ax.grid(True, alpha=0.3)
plt.tight_layout()
plt.savefig("05_cumulative_return.png", dpi=100)
print("已保存: 05_cumulative_return.png")
plt.close()

# ============================================
# 7. 专业 K 线图（mplfinance）
# ============================================

print("=== 图6: 专业 K 线图 ===")

try:
    import mplfinance as mpf

    # 取最近 60 天数据画 K 线
    df_kline = df.tail(60).copy()

    # 确保列名符合 mplfinance 要求
    df_kline.columns = [c[0] if isinstance(c, tuple) else c for c in df_kline.columns]

    # 添加均线
    apds = [
        mpf.make_addplot(df_kline["MA20"].tail(60), color="orange", width=1),
    ]

    # 画 K 线图
    mpf.plot(
        df_kline,
        type="candle",           # K 线图类型：candle(蜡烛图), ohlc, line
        style="charles",          # 样式：charles, yahoo, nightclouds
        title="AAPL K线图 (近60天)",
        ylabel="价格 ($)",
        volume=True,              # 显示成交量
        figsize=(14, 8),
        savefig="06_candlestick.png",
    )
    print("已保存: 06_candlestick.png")

except ImportError:
    print("mplfinance 未安装，跳过 K 线图")
    print("安装命令: pip install mplfinance")
except Exception as e:
    print(f"K 线图生成失败: {e}")

# ============================================
# 8. 多股票对比
# ============================================

print("=== 图7: 多股票收益率对比 ===")

tickers = ["AAPL", "GOOGL", "MSFT", "NVDA"]
print(f"正在下载 {tickers} 的数据...")
multi_data = yf.download(tickers, period="6mo")

if not multi_data.empty:
    closes = multi_data["Close"]
    # 归一化到起始点=100（方便对比）
    normalized = closes / closes.iloc[0] * 100

    fig, ax = plt.subplots(figsize=(12, 6))
    for ticker in tickers:
        if ticker in normalized.columns:
            ax.plot(normalized.index, normalized[ticker], label=ticker, linewidth=1.5)

    ax.axhline(y=100, color="gray", linestyle="--", linewidth=0.5)
    ax.set_title("科技股走势对比（归一化）", fontsize=16)
    ax.set_xlabel("日期")
    ax.set_ylabel("相对价格（起始=100）")
    ax.legend()
    ax.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig("07_stock_comparison.png", dpi=100)
    print("已保存: 07_stock_comparison.png")
    plt.close()

print()

# ============================================
# 清理提示
# ============================================

print("=" * 50)
print("可视化教程完成！")
print()
print("生成的图片文件：")
print("  01_close_price.png       - 收盘价折线图")
print("  02_price_with_ma.png     - 价格+均线")
print("  03_price_volume.png      - 价格+成交量")
print("  04_return_distribution.png - 收益率分布")
print("  05_cumulative_return.png - 累计收益率")
print("  06_candlestick.png       - 专业K线图")
print("  07_stock_comparison.png  - 多股对比")
print()
print("提示：图片在当前目录下，可以用 open *.png 查看")
print()
print("下一步：进入 02-technical-indicators/ 学习技术指标！")
print("=" * 50)
