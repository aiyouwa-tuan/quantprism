"""
==============================================
获取加密货币行情数据 - ccxt 库
==============================================

学习目标：
- 使用 ccxt 库连接交易所
- 获取实时价格
- 获取历史 K 线 (OHLCV) 数据
- 将数据保存为 pandas DataFrame

前置要求：
    pip install ccxt pandas

运行方式：
    python 01_crypto_data.py

重要说明：
- ccxt 是开源库，支持 100+ 个交易所
- 获取行情数据不需要 API Key（只读操作）
- 交易（下单）才需要 API Key
"""

import ccxt
import pandas as pd
from datetime import datetime

# ============================================
# 1. 查看支持的交易所
# ============================================

print("=== ccxt 支持的交易所 ===")
exchanges = ccxt.exchanges  # 所有支持的交易所列表
print(f"支持 {len(exchanges)} 个交易所")
print(f"前10个: {exchanges[:10]}")
print()

# ============================================
# 2. 连接交易所（以 Binance 为例）
# ============================================

print("=== 连接 Binance 交易所 ===")

# 创建交易所实例（不需要 API Key）
exchange = ccxt.binance({
    "enableRateLimit": True,  # 启用请求频率限制，避免被封 IP
})

# 加载交易对信息
exchange.load_markets()
print(f"可交易品种数量: {len(exchange.markets)}")

# 查看一些热门交易对
popular_pairs = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "DOGE/USDT"]
for pair in popular_pairs:
    if pair in exchange.markets:
        print(f"  ✓ {pair} 可交易")
print()

# ============================================
# 3. 获取实时价格（Ticker）
# ============================================

print("=== 获取实时价格 ===")

try:
    ticker = exchange.fetch_ticker("BTC/USDT")

    print(f"交易对: BTC/USDT")
    print(f"最新价: ${ticker['last']:,.2f}")
    print(f"24h最高: ${ticker['high']:,.2f}")
    print(f"24h最低: ${ticker['low']:,.2f}")
    print(f"24h成交量: {ticker['baseVolume']:,.2f} BTC")
    print(f"24h涨跌幅: {ticker['percentage']:+.2f}%")
except Exception as e:
    print(f"获取实时数据失败（可能是网络问题）: {e}")
    print("提示：如果在国内，可能需要代理才能访问 Binance API")

print()

# ============================================
# 4. 获取历史 K 线数据 (OHLCV)
# ============================================

print("=== 获取历史 K 线数据 ===")
print("OHLCV = Open(开盘), High(最高), Low(最低), Close(收盘), Volume(成交量)")
print()

try:
    # 获取 BTC/USDT 日线数据，最近 100 根 K 线
    ohlcv = exchange.fetch_ohlcv(
        symbol="BTC/USDT",
        timeframe="1d",     # 时间周期：1m/5m/15m/1h/4h/1d/1w
        limit=100,          # 获取数量
    )

    # 转为 pandas DataFrame
    df = pd.DataFrame(ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df["date"] = pd.to_datetime(df["timestamp"], unit="ms")  # 时间戳转日期
    df = df.set_index("date")
    df = df.drop("timestamp", axis=1)

    print(f"获取到 {len(df)} 根日线 K 线")
    print(f"时间范围: {df.index[0].strftime('%Y-%m-%d')} ~ {df.index[-1].strftime('%Y-%m-%d')}")
    print()
    print("最近 5 天数据:")
    print(df.tail().round(2))
    print()

    # 简单统计
    print("=== 数据统计 ===")
    df["daily_return"] = df["close"].pct_change() * 100
    print(f"平均日收益率: {df['daily_return'].mean():.4f}%")
    print(f"日收益率标准差: {df['daily_return'].std():.4f}%")
    print(f"最大单日涨幅: {df['daily_return'].max():.2f}%")
    print(f"最大单日跌幅: {df['daily_return'].min():.2f}%")
    print(f"区间最高价: ${df['high'].max():,.2f}")
    print(f"区间最低价: ${df['low'].min():,.2f}")

    # 保存到 CSV
    save_path = "btc_daily.csv"
    df.to_csv(save_path)
    print(f"\n数据已保存到: {save_path}")

except Exception as e:
    print(f"获取历史数据失败: {e}")
    print("提示：请检查网络连接，或尝试使用其他交易所")

print()

# ============================================
# 5. 获取多个交易对数据
# ============================================

print("=== 批量获取多币种数据 ===")

symbols = ["BTC/USDT", "ETH/USDT", "SOL/USDT"]
summary = []

for symbol in symbols:
    try:
        ohlcv = exchange.fetch_ohlcv(symbol, "1d", limit=30)
        df_temp = pd.DataFrame(ohlcv, columns=["ts", "open", "high", "low", "close", "volume"])

        # 计算 30 日收益率
        first_close = df_temp["close"].iloc[0]
        last_close = df_temp["close"].iloc[-1]
        ret_30d = (last_close - first_close) / first_close * 100

        summary.append({
            "symbol": symbol,
            "price": last_close,
            "30d_return": ret_30d,
            "30d_high": df_temp["high"].max(),
            "30d_low": df_temp["low"].min(),
        })

        print(f"  ✓ {symbol}: ${last_close:,.2f} (30日: {ret_30d:+.2f}%)")

    except Exception as e:
        print(f"  ✗ {symbol}: 获取失败 - {e}")

print()

# ============================================
# 6. 不同时间周期
# ============================================

print("=== 支持的时间周期 ===")
print("""
  1m   = 1 分钟    适合高频/超短线
  5m   = 5 分钟    适合短线
  15m  = 15 分钟   适合日内交易
  1h   = 1 小时    适合波段
  4h   = 4 小时    适合中线
  1d   = 1 天      适合趋势跟踪
  1w   = 1 周      适合长线
""")

# ============================================
# 7. 使用其他交易所（如果 Binance 无法访问）
# ============================================

print("=== 备选交易所 ===")
print("""
如果 Binance 无法访问，可以替换交易所：

  # OKX（原 OKEx）
  exchange = ccxt.okx({"enableRateLimit": True})

  # Bybit
  exchange = ccxt.bybit({"enableRateLimit": True})

  # Gate.io
  exchange = ccxt.gate({"enableRateLimit": True})

  # Coinbase（美国用户）
  exchange = ccxt.coinbase({"enableRateLimit": True})

代码其余部分完全不用改，这就是 ccxt 的强大之处！
""")

print("=" * 50)
print("第 1 节完成！")
print("下一节：02_us_stock_data.py（美股数据获取）")
print("=" * 50)
