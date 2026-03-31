"""
==============================================
第 3 课：函数 - 把代码打包复用
==============================================

学习目标：
- 定义和调用函数
- 参数和返回值
- 默认参数
- 函数的实际应用

量化交易关联：
- 把"计算指标"、"生成信号"、"下单"等封装成函数
- 函数让你的策略代码清晰、可复用、易修改

运行方式：
    python 03_functions.py
"""

# ============================================
# 1. 最简单的函数
# ============================================

print("=== 基础函数 ===")

# def 关键字定义函数
def say_hello():
    print("Hello, 量化交易！")

# 调用函数
say_hello()
print()

# ============================================
# 2. 带参数的函数
# ============================================

print("=== 带参数的函数 ===")

def calculate_profit(buy_price, sell_price, shares):
    """计算交易盈亏

    参数:
        buy_price: 买入价格
        sell_price: 卖出价格
        shares: 交易数量
    返回:
        (盈亏金额, 收益率)
    """
    profit = (sell_price - buy_price) * shares
    profit_rate = (sell_price - buy_price) / buy_price * 100
    return profit, profit_rate  # 返回多个值

# 调用函数
amount, rate = calculate_profit(150.0, 178.52, 100)
print(f"盈亏金额: ${amount:.2f}")
print(f"收益率: {rate:.2f}%")
print()

# ============================================
# 3. 默认参数
# ============================================

print("=== 默认参数 ===")

def calculate_sma(prices, window=20):
    """计算简单移动平均线 (SMA)

    参数:
        prices: 价格列表
        window: 窗口大小，默认 20
    """
    if len(prices) < window:
        return None
    return sum(prices[-window:]) / window

prices = [100, 102, 101, 105, 103, 107, 106, 110, 108, 112]

sma5 = calculate_sma(prices, window=5)     # 指定 window=5
sma_default = calculate_sma(prices)         # 使用默认值 20（数据不够会返回 None）

print(f"SMA(5) = {sma5:.2f}")
print(f"SMA(20) = {sma_default}")  # None，因为数据不足 20 条
print()

# ============================================
# 4. 实战：交易信号生成函数
# ============================================

print("=== 实战：交易信号生成器 ===")

def generate_ma_signal(prices, short_window=5, long_window=10):
    """双均线交叉策略信号

    短期均线上穿长期均线 → 买入 (金叉)
    短期均线下穿长期均线 → 卖出 (死叉)

    参数:
        prices: 价格列表
        short_window: 短期均线周期
        long_window: 长期均线周期
    返回:
        信号字符串
    """
    if len(prices) < long_window:
        return "数据不足，无法判断"

    # 计算短期和长期均线
    short_ma = sum(prices[-short_window:]) / short_window
    long_ma = sum(prices[-long_window:]) / long_window

    print(f"  短期 MA({short_window}) = {short_ma:.2f}")
    print(f"  长期 MA({long_window}) = {long_ma:.2f}")

    if short_ma > long_ma:
        return "买入信号 (金叉：短期均线 > 长期均线)"
    elif short_ma < long_ma:
        return "卖出信号 (死叉：短期均线 < 长期均线)"
    else:
        return "观望 (均线重合)"

# 模拟上涨趋势的价格
uptrend_prices = [100, 101, 99, 102, 104, 103, 106, 108, 107, 110, 112, 115]
print("上涨趋势:")
signal = generate_ma_signal(uptrend_prices)
print(f"  信号: {signal}")
print()

# 模拟下跌趋势的价格
downtrend_prices = [115, 112, 113, 110, 108, 109, 106, 104, 105, 102, 100, 98]
print("下跌趋势:")
signal = generate_ma_signal(downtrend_prices)
print(f"  信号: {signal}")
print()

# ============================================
# 5. 实战：风险计算函数
# ============================================

print("=== 风险计算函数 ===")

def calculate_max_drawdown(prices):
    """计算最大回撤

    最大回撤 = 从最高点到最低点的最大跌幅
    这是衡量风险的重要指标

    参数:
        prices: 价格列表
    返回:
        最大回撤百分比（负数）
    """
    max_price = prices[0]     # 记录历史最高价
    max_drawdown = 0          # 记录最大回撤

    for price in prices:
        if price > max_price:
            max_price = price  # 更新最高价

        # 计算当前回撤
        drawdown = (price - max_price) / max_price * 100
        if drawdown < max_drawdown:
            max_drawdown = drawdown  # 更新最大回撤

    return max_drawdown

# 测试
test_prices = [100, 110, 120, 105, 115, 90, 95, 100]
mdd = calculate_max_drawdown(test_prices)
print(f"价格序列: {test_prices}")
print(f"最大回撤: {mdd:.2f}%")
print("(从 120 跌到 90，回撤 = -25%)")
print()

# ============================================
# 6. 函数组合使用
# ============================================

print("=== 函数组合：简单策略回测 ===")

def simple_backtest(prices, buy_threshold=-0.02, sell_threshold=0.03):
    """极简回测：跌 2% 买入，涨 3% 卖出

    参数:
        prices: 价格列表
        buy_threshold: 买入阈值（日跌幅）
        sell_threshold: 卖出阈值（累计涨幅）
    """
    holding = False
    buy_price = 0
    trades = []

    for i in range(1, len(prices)):
        daily_return = (prices[i] - prices[i-1]) / prices[i-1]

        if not holding and daily_return < buy_threshold:
            # 日跌幅超过阈值，买入
            buy_price = prices[i]
            holding = True
            print(f"  第{i}天 买入 @ ${buy_price:.2f}")

        elif holding:
            profit_rate = (prices[i] - buy_price) / buy_price
            if profit_rate > sell_threshold:
                # 累计涨幅超过阈值，卖出
                holding = False
                trades.append(profit_rate * 100)
                print(f"  第{i}天 卖出 @ ${prices[i]:.2f}, 收益: {profit_rate*100:.2f}%")

    # 统计结果
    if trades:
        print(f"\n  交易次数: {len(trades)}")
        print(f"  平均收益: {sum(trades)/len(trades):.2f}%")
        print(f"  总收益: {sum(trades):.2f}%")
    else:
        print("\n  没有产生交易")

# 模拟 20 天价格
import random
random.seed(123)
sim_prices = [100]
for _ in range(30):
    change = random.uniform(-0.04, 0.04)
    sim_prices.append(sim_prices[-1] * (1 + change))

simple_backtest(sim_prices)

print()
print("=" * 50)
print("恭喜！第 3 课完成！")
print("下一课：04_data_structures.py（数据结构）")
print("=" * 50)
