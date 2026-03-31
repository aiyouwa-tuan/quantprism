"""
==============================================
第 4 课：数据结构 - 列表、字典、元组
==============================================

学习目标：
- 列表 (list)：有序的数据集合
- 字典 (dict)：键值对的数据集合
- 元组 (tuple)：不可变的列表
- 集合 (set)：去重集合

量化交易关联：
- 列表：存储价格序列、交易记录
- 字典：存储股票信息（代码→价格）、策略参数
- 集合：去重（持仓列表）

运行方式：
    python 04_data_structures.py
"""

# ============================================
# 1. 列表 (list) - 最常用的数据结构
# ============================================

print("=== 列表基础 ===")

# 创建列表
prices = [100.0, 102.5, 99.8, 105.3, 103.1]
symbols = ["AAPL", "GOOGL", "MSFT", "TSLA"]

print(f"价格列表: {prices}")
print(f"股票列表: {symbols}")

# 访问元素（索引从 0 开始）
print(f"\n第一个价格: {prices[0]}")   # 100.0
print(f"最后一个价格: {prices[-1]}")  # 103.1（-1 表示最后一个）

# 切片（取一段）
print(f"前3个价格: {prices[:3]}")     # [100.0, 102.5, 99.8]
print(f"后2个价格: {prices[-2:]}")    # [103.1]

# 添加和删除
prices.append(106.2)       # 添加到末尾
print(f"添加后: {prices}")

prices.pop()               # 删除末尾
print(f"删除后: {prices}")

# 常用操作
print(f"\n长度: {len(prices)}")
print(f"最高价: {max(prices)}")
print(f"最低价: {min(prices)}")
print(f"平均价: {sum(prices) / len(prices):.2f}")

# 排序
sorted_prices = sorted(prices)              # 返回新列表，不改变原列表
print(f"升序排列: {sorted_prices}")
print(f"降序排列: {sorted(prices, reverse=True)}")
print()

# ============================================
# 2. 字典 (dict) - 键值对
# ============================================

print("=== 字典基础 ===")

# 创建字典：{键: 值}
portfolio = {
    "AAPL": {"shares": 100, "avg_cost": 150.0},
    "BTC":  {"shares": 2,   "avg_cost": 60000.0},
    "ETH":  {"shares": 10,  "avg_cost": 3000.0},
}

# 访问
print(f"持仓: {list(portfolio.keys())}")
print(f"AAPL 持仓: {portfolio['AAPL']}")
print(f"AAPL 数量: {portfolio['AAPL']['shares']}")

# 添加新持仓
portfolio["GOOGL"] = {"shares": 50, "avg_cost": 140.0}
print(f"\n添加 GOOGL 后: {list(portfolio.keys())}")

# 遍历字典
print("\n--- 持仓明细 ---")
for symbol, info in portfolio.items():
    value = info["shares"] * info["avg_cost"]
    print(f"  {symbol}: {info['shares']} 股 × ${info['avg_cost']:.0f} = ${value:,.0f}")

# 检查键是否存在
if "TSLA" in portfolio:
    print("持有 TSLA")
else:
    print("\n未持有 TSLA")

# 安全获取（不存在时返回默认值，不会报错）
tsla_info = portfolio.get("TSLA", {"shares": 0, "avg_cost": 0})
print(f"TSLA 信息: {tsla_info}")
print()

# ============================================
# 3. 元组 (tuple) - 不可变列表
# ============================================

print("=== 元组 ===")

# 元组用圆括号，创建后不能修改
trade = ("AAPL", "BUY", 150.0, 100)  # (代码, 方向, 价格, 数量)

symbol, direction, price, qty = trade  # 解包
print(f"交易: {direction} {qty} 股 {symbol} @ ${price}")

# 元组常用于函数返回多个值
def get_price_range(prices):
    return min(prices), max(prices)  # 返回元组

low, high = get_price_range([100, 105, 98, 110, 103])
print(f"价格区间: ${low} ~ ${high}")
print()

# ============================================
# 4. 集合 (set) - 去重
# ============================================

print("=== 集合 ===")

# 今日交易过的股票
trades_today = ["AAPL", "BTC", "AAPL", "ETH", "BTC", "AAPL"]
unique_symbols = set(trades_today)  # 自动去重
print(f"交易记录: {trades_today}")
print(f"交易品种（去重）: {unique_symbols}")
print(f"交易品种数: {len(unique_symbols)}")

# 集合运算
watchlist = {"AAPL", "GOOGL", "MSFT", "TSLA"}
holdings = {"AAPL", "BTC", "ETH"}

print(f"\n关注列表: {watchlist}")
print(f"持仓列表: {holdings}")
print(f"关注且持有: {watchlist & holdings}")         # 交集
print(f"关注但未持有: {watchlist - holdings}")        # 差集
print(f"所有相关品种: {watchlist | holdings}")        # 并集
print()

# ============================================
# 5. 实战：用字典构建交易日志
# ============================================

print("=== 实战：交易日志 ===")

trade_log = []  # 用列表存储多笔交易

# 添加交易记录
def add_trade(log, symbol, side, price, quantity):
    """记录一笔交易"""
    trade = {
        "symbol": symbol,
        "side": side,       # BUY 或 SELL
        "price": price,
        "quantity": quantity,
        "value": price * quantity,
    }
    log.append(trade)
    return trade

add_trade(trade_log, "AAPL", "BUY", 150.0, 100)
add_trade(trade_log, "BTC", "BUY", 63000.0, 0.5)
add_trade(trade_log, "AAPL", "SELL", 178.0, 100)

# 打印交易日志
print(f"{'品种':<8} {'方向':<6} {'价格':>10} {'数量':>8} {'金额':>12}")
print("-" * 50)
for t in trade_log:
    print(f"{t['symbol']:<8} {t['side']:<6} ${t['price']:>9,.2f} {t['quantity']:>8} ${t['value']:>11,.2f}")

# 统计
buy_total = sum(t["value"] for t in trade_log if t["side"] == "BUY")
sell_total = sum(t["value"] for t in trade_log if t["side"] == "SELL")
print(f"\n买入总额: ${buy_total:,.2f}")
print(f"卖出总额: ${sell_total:,.2f}")

# ============================================
# 6. 嵌套数据结构（实际项目中很常见）
# ============================================

print("\n=== 嵌套数据结构 ===")

# 模拟 API 返回的 K 线数据
kline_data = [
    {"date": "2024-01-01", "open": 100, "high": 105, "low": 98,  "close": 103, "volume": 1000000},
    {"date": "2024-01-02", "open": 103, "high": 108, "low": 102, "close": 107, "volume": 1200000},
    {"date": "2024-01-03", "open": 107, "high": 110, "low": 104, "close": 105, "volume": 900000},
]

# 从 K 线数据中提取收盘价列表
closes = [k["close"] for k in kline_data]
volumes = [k["volume"] for k in kline_data]

print(f"收盘价: {closes}")
print(f"平均成交量: {sum(volumes) / len(volumes):,.0f}")

# 找出成交量最大的那天
max_vol_day = max(kline_data, key=lambda x: x["volume"])
print(f"最大成交量日: {max_vol_day['date']} (成交量: {max_vol_day['volume']:,})")

print()
print("=" * 50)
print("恭喜！第 4 课完成！")
print("下一课：05_pandas_numpy.py（pandas & numpy）")
print("=" * 50)
