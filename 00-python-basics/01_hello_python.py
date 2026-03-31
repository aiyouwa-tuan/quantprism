"""
==============================================
第 1 课：Python 入门 - 变量与数据类型
==============================================

学习目标：
- 理解什么是变量
- 掌握基本数据类型：整数、浮点数、字符串、布尔值
- 学会使用 print() 输出信息
- 学会基本的数学运算

运行方式：
    python 01_hello_python.py

量化交易关联：
- 价格是浮点数 (float)
- 成交量是整数 (int)
- 股票代码是字符串 (str)
- 买卖信号是布尔值 (bool)
"""

# ============================================
# 1. print() - 打印输出
# ============================================
# print() 是最基础的函数，用来在屏幕上显示信息

print("Hello, 量化交易！")
print("这是我的第一行 Python 代码")
print()  # 打印空行

# ============================================
# 2. 变量 - 给数据取个名字
# ============================================
# 变量就像一个盒子，你可以把数据放进去，之后用名字来取出

# 股票代码（字符串 str）—— 用引号包裹
stock_code = "AAPL"          # 苹果公司
crypto_symbol = "BTC/USDT"   # 比特币对 USDT

# 价格（浮点数 float）—— 带小数点的数字
stock_price = 178.52
btc_price = 65432.10

# 持仓数量（整数 int）—— 没有小数点的数字
shares = 100        # 持有 100 股
btc_amount = 2      # 持有 2 个 BTC

# 是否持仓（布尔值 bool）—— 只有 True 或 False
is_holding = True   # 正在持仓
should_sell = False  # 不应该卖

print("=== 我的持仓信息 ===")
print("股票代码:", stock_code)
print("股票价格:", stock_price)
print("持有数量:", shares)
print("是否持仓:", is_holding)
print()

# ============================================
# 3. 数据类型查看 - type()
# ============================================
# type() 可以告诉你一个变量是什么类型

print("=== 数据类型 ===")
print(f"stock_code 的类型: {type(stock_code)}")   # <class 'str'>
print(f"stock_price 的类型: {type(stock_price)}")  # <class 'float'>
print(f"shares 的类型: {type(shares)}")            # <class 'int'>
print(f"is_holding 的类型: {type(is_holding)}")    # <class 'bool'>
print()

# 小知识：f"..." 叫做 f-string，可以在字符串中嵌入变量
# {变量名} 会被替换成变量的值

# ============================================
# 4. 数学运算 - 计算持仓市值
# ============================================

print("=== 数学运算 ===")

# 基本运算
total_value = stock_price * shares   # 乘法：单价 × 数量
print(f"股票市值: ${total_value}")

btc_value = btc_price * btc_amount
print(f"BTC 市值: ${btc_value}")

# 总资产
total_assets = total_value + btc_value
print(f"总资产: ${total_assets}")

# 常用运算符
print()
print("=== 常用运算符 ===")
print(f"加法: 10 + 3 = {10 + 3}")      # 13
print(f"减法: 10 - 3 = {10 - 3}")      # 7
print(f"乘法: 10 * 3 = {10 * 3}")      # 30
print(f"除法: 10 / 3 = {10 / 3}")      # 3.333...
print(f"整除: 10 // 3 = {10 // 3}")    # 3（去掉小数）
print(f"取余: 10 % 3 = {10 % 3}")      # 1（余数）
print(f"幂运算: 2 ** 10 = {2 ** 10}")   # 1024
print()

# ============================================
# 5. 实战练习：计算收益率
# ============================================

print("=== 实战：计算收益率 ===")

buy_price = 150.00    # 买入价
sell_price = 178.52   # 卖出价（当前价）

# 收益率 = (卖出价 - 买入价) / 买入价 × 100%
profit = sell_price - buy_price
profit_rate = (profit / buy_price) * 100

print(f"买入价: ${buy_price}")
print(f"卖出价: ${sell_price}")
print(f"盈亏金额: ${profit:.2f}")           # :.2f 表示保留2位小数
print(f"收益率: {profit_rate:.2f}%")
print()

# ============================================
# 6. 字符串操作（处理股票代码常用）
# ============================================

print("=== 字符串操作 ===")

symbol = "  aapl  "
print(f"原始: '{symbol}'")
print(f"去空格: '{symbol.strip()}'")          # 去掉两端空格
print(f"转大写: '{symbol.strip().upper()}'")   # 转大写

# 拼接字符串
exchange = "NASDAQ"
full_name = exchange + ":" + symbol.strip().upper()
print(f"完整代码: {full_name}")

# ============================================
# 7. 类型转换
# ============================================

print()
print("=== 类型转换 ===")

# 字符串 → 数字（从文件或API读取的数据经常是字符串）
price_str = "178.52"
price_num = float(price_str)   # 字符串转浮点数
print(f"字符串 '{price_str}' → 浮点数 {price_num}")

volume_str = "1000000"
volume_num = int(volume_str)   # 字符串转整数
print(f"字符串 '{volume_str}' → 整数 {volume_num}")

# 数字 → 字符串
print(f"浮点数 {price_num} → 字符串 '{str(price_num)}'")

print()
print("=" * 50)
print("恭喜！第 1 课完成！")
print("下一课：02_control_flow.py（流程控制）")
print("=" * 50)
