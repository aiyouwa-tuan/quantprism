"""
==============================================
第 2 课：流程控制 - if/for/while
==============================================

学习目标：
- if/elif/else 条件判断
- for 循环遍历
- while 循环
- 比较运算符和逻辑运算符

量化交易关联：
- if：判断买卖信号（价格 > 均线 → 买入）
- for：遍历历史数据计算指标
- while：持续监控行情直到触发条件

运行方式：
    python 02_control_flow.py
"""

# ============================================
# 1. 比较运算符
# ============================================

print("=== 比较运算符 ===")

price = 178.52
target_price = 180.00

print(f"当前价格: {price}")
print(f"目标价格: {target_price}")
print(f"price > target:  {price > target_price}")    # 大于
print(f"price < target:  {price < target_price}")    # 小于
print(f"price >= target: {price >= target_price}")   # 大于等于
print(f"price == target: {price == target_price}")   # 等于（注意是两个等号）
print(f"price != target: {price != target_price}")   # 不等于
print()

# ============================================
# 2. if / elif / else - 条件判断
# ============================================

print("=== 交易信号判断 ===")

rsi = 25  # RSI 指标值（0-100）

# RSI < 30: 超卖 → 考虑买入
# RSI > 70: 超买 → 考虑卖出
# 其他: 观望

if rsi < 30:
    signal = "买入信号 (超卖)"
elif rsi > 70:
    signal = "卖出信号 (超买)"
else:
    signal = "观望 (中性区间)"

print(f"RSI = {rsi}")
print(f"交易信号: {signal}")
print()

# 注意：Python 用缩进（4个空格）来表示代码块，不用大括号

# ============================================
# 3. 逻辑运算符：and, or, not
# ============================================

print("=== 多条件组合判断 ===")

price = 65000
volume = 5000000000  # 50亿成交量
ma20 = 63000         # 20日均线

# 多个条件同时满足才买入
if price > ma20 and volume > 1000000000:
    print("✓ 满足买入条件：价格在均线上方 + 成交量放大")
else:
    print("✗ 不满足买入条件")

# 任一条件满足就预警
if price > 70000 or price < 55000:
    print("⚠ 价格异常波动预警！")
else:
    print("✓ 价格在正常范围内")

# not 取反
is_bear_market = False
if not is_bear_market:
    print("✓ 当前不是熊市，可以正常交易")

print()

# ============================================
# 4. for 循环 - 遍历数据
# ============================================

print("=== for 循环：遍历价格数据 ===")

# 模拟一周的 BTC 收盘价
daily_prices = [64500, 65200, 63800, 66100, 65432]
days = ["周一", "周二", "周三", "周四", "周五"]

# 遍历价格列表
for i in range(len(daily_prices)):
    print(f"  {days[i]}: ${daily_prices[i]}")

print()

# 更 Pythonic 的写法：zip 同时遍历两个列表
print("--- 用 zip 同时遍历 ---")
for day, price in zip(days, daily_prices):
    print(f"  {day}: ${price}")

print()

# ============================================
# 5. for 循环：计算简单移动平均线 (SMA)
# ============================================

print("=== 实战：手动计算 3 日移动平均线 ===")

prices = [100, 102, 101, 105, 103, 107, 106, 110, 108, 112]

# 3日移动平均线 = 最近3天价格的平均值
window = 3

for i in range(window - 1, len(prices)):
    # 取最近 window 天的价格
    window_prices = prices[i - window + 1 : i + 1]
    sma = sum(window_prices) / window
    print(f"  第{i+1}天: 价格={prices[i]}, SMA({window})={sma:.2f}")

print()

# ============================================
# 6. for 循环：统计涨跌天数
# ============================================

print("=== 统计涨跌天数 ===")

up_days = 0
down_days = 0

for i in range(1, len(daily_prices)):
    if daily_prices[i] > daily_prices[i - 1]:
        up_days += 1   # += 1 等于 up_days = up_days + 1
    elif daily_prices[i] < daily_prices[i - 1]:
        down_days += 1

print(f"上涨天数: {up_days}")
print(f"下跌天数: {down_days}")
print(f"胜率: {up_days / (up_days + down_days) * 100:.1f}%")
print()

# ============================================
# 7. while 循环 - 持续监控
# ============================================

print("=== while 循环：模拟价格监控 ===")

# 模拟价格变动
import random
random.seed(42)  # 固定随机种子，每次运行结果相同

current_price = 100.0
stop_loss = 95.0       # 止损价
take_profit = 110.0    # 止盈价
day = 0

while True:
    day += 1
    # 模拟每日价格变动（-3% ~ +3%）
    change = random.uniform(-0.03, 0.03)
    current_price *= (1 + change)

    print(f"  第{day}天: 价格 ${current_price:.2f}")

    if current_price <= stop_loss:
        print(f"  ⚠ 触发止损！止损价 ${stop_loss}")
        break  # break 跳出循环

    if current_price >= take_profit:
        print(f"  ✓ 触发止盈！止盈价 ${take_profit}")
        break

    if day >= 30:
        print(f"  ⏰ 持仓 30 天未触发止损/止盈，平仓退出")
        break

profit_rate = (current_price - 100) / 100 * 100
print(f"  最终收益率: {profit_rate:.2f}%")
print()

# ============================================
# 8. 列表推导式（Python 特有的简洁写法）
# ============================================

print("=== 列表推导式 ===")

prices = [100, 102, 101, 105, 103]

# 传统写法
daily_returns = []
for i in range(1, len(prices)):
    ret = (prices[i] - prices[i-1]) / prices[i-1] * 100
    daily_returns.append(ret)

# 列表推导式（一行搞定，效果完全一样）
daily_returns2 = [(prices[i] - prices[i-1]) / prices[i-1] * 100
                  for i in range(1, len(prices))]

print(f"每日收益率: {[f'{r:.2f}%' for r in daily_returns]}")

# 筛选出上涨的日子
up_returns = [r for r in daily_returns if r > 0]
print(f"上涨日收益率: {[f'{r:.2f}%' for r in up_returns]}")

print()
print("=" * 50)
print("恭喜！第 2 课完成！")
print("下一课：03_functions.py（函数）")
print("=" * 50)
