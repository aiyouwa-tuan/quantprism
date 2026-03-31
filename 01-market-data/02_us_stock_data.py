"""
==============================================
获取美股行情数据 - yfinance 库
==============================================

学习目标：
- 使用 yfinance 获取美股历史数据
- 获取单只和多只股票数据
- 获取公司基本面信息
- 数据清洗与预处理

前置要求：
    pip install yfinance pandas

运行方式：
    python 02_us_stock_data.py

说明：
- yfinance 是非官方的 Yahoo Finance API 封装
- 完全免费，不需要注册或 API Key
- 数据延迟约 15 分钟（非实时）
- 适合学习和回测，不适合高频实盘
"""

import yfinance as yf
import pandas as pd

# ============================================
# 1. 获取单只股票数据
# ============================================

print("=== 获取苹果 (AAPL) 股票数据 ===")

# 下载 AAPL 最近 1 年的日线数据
aapl = yf.download("AAPL", period="1y")

print(f"数据形状: {aapl.shape}")
print(f"时间范围: {aapl.index[0].strftime('%Y-%m-%d')} ~ {aapl.index[-1].strftime('%Y-%m-%d')}")
print()
print("最近 5 天:")
print(aapl.tail())
print()

# ============================================
# 2. 自定义时间范围
# ============================================

print("=== 自定义时间范围 ===")

# 指定开始和结束日期
df = yf.download("AAPL", start="2024-01-01", end="2024-12-31")
print(f"2024年 AAPL 数据: {len(df)} 个交易日")
print()

# period 参数的选项：
# 1d, 5d, 1mo, 3mo, 6mo, 1y, 2y, 5y, 10y, ytd, max
print("period 参数选项:")
print("  1d/5d     = 最近 1/5 天")
print("  1mo/3mo   = 最近 1/3 个月")
print("  6mo/1y/2y = 最近 6个月/1年/2年")
print("  ytd       = 今年至今")
print("  max       = 所有历史数据")
print()

# ============================================
# 3. 不同时间周期
# ============================================

print("=== 不同时间周期 ===")

# 周线数据
weekly = yf.download("AAPL", period="6mo", interval="1wk")
print(f"周线数据: {len(weekly)} 根K线")

# 小时线（最多获取最近 730 天）
hourly = yf.download("AAPL", period="5d", interval="1h")
print(f"小时线数据: {len(hourly)} 根K线")

# interval 选项: 1m, 2m, 5m, 15m, 30m, 60m, 90m, 1h, 1d, 5d, 1wk, 1mo, 3mo
print()

# ============================================
# 4. 批量下载多只股票
# ============================================

print("=== 批量下载：科技巨头 ===")

tickers = ["AAPL", "GOOGL", "MSFT", "AMZN", "NVDA"]
data = yf.download(tickers, period="1y")

# 提取收盘价
closes = data["Close"]
print(f"获取到 {len(closes)} 天的收盘价数据")
print()
print("最近 5 天收盘价:")
print(closes.tail().round(2))
print()

# 计算各股票收益率
returns = closes.pct_change()
total_return = (closes.iloc[-1] / closes.iloc[0] - 1) * 100

print("=== 1 年收益率排名 ===")
for ticker in total_return.sort_values(ascending=False).index:
    print(f"  {ticker}: {total_return[ticker]:+.2f}%")
print()

# ============================================
# 5. 获取公司基本面信息
# ============================================

print("=== 公司基本面信息（AAPL）===")

stock = yf.Ticker("AAPL")

info = stock.info
print(f"公司名称: {info.get('longName', 'N/A')}")
print(f"行业: {info.get('industry', 'N/A')}")
print(f"市值: ${info.get('marketCap', 0)/1e9:.0f}B")
print(f"市盈率 (PE): {info.get('trailingPE', 'N/A')}")
print(f"股息率: {info.get('dividendYield', 0)*100:.2f}%")
print(f"52周最高: ${info.get('fiftyTwoWeekHigh', 'N/A')}")
print(f"52周最低: ${info.get('fiftyTwoWeekLow', 'N/A')}")
print()

# ============================================
# 6. 数据预处理（实际使用中很重要）
# ============================================

print("=== 数据预处理 ===")

df = yf.download("AAPL", period="1y")

# 检查缺失值
missing = df.isnull().sum()
print(f"缺失值:\n{missing}")
print()

# 填充缺失值（前向填充：用前一天的值填充）
df = df.ffill()

# 添加常用计算列
df["daily_return"] = df["Close"].pct_change() * 100
df["cum_return"] = (1 + df["Close"].pct_change()).cumprod() - 1
df["MA20"] = df["Close"].rolling(window=20).mean()
df["MA50"] = df["Close"].rolling(window=50).mean()
df["volatility_20d"] = df["daily_return"].rolling(window=20).std()

print("添加计算列后的数据:")
print(df[["Close", "daily_return", "cum_return", "MA20", "MA50"]].tail().round(2))
print()

# ============================================
# 7. 保存数据
# ============================================

save_path = "aapl_daily.csv"
df.to_csv(save_path)
print(f"数据已保存到: {save_path}")

# 清理
import os
os.remove(save_path)
print("临时文件已清理")
print()

# ============================================
# 8. 常用美股代码参考
# ============================================

print("=== 常用美股代码 ===")
print("""
科技股:
  AAPL  苹果      GOOGL 谷歌      MSFT  微软
  AMZN  亚马逊    NVDA  英伟达    META  Meta
  TSLA  特斯拉    NFLX  Netflix

ETF（指数基金）:
  SPY   标普500   QQQ   纳斯达克100  DIA   道琼斯
  IWM   罗素2000  VTI   全美股市

加密货币相关:
  COIN  Coinbase  MSTR  MicroStrategy
  BITO  比特币期货ETF

波动率:
  VIX   恐慌指数（^VIX）
""")

print("=" * 50)
print("第 2 节完成！")
print("下一节：03_data_visualization.py（数据可视化）")
print("=" * 50)
