"""
==============================================
第 5 课：pandas & numpy - 量化交易的核心工具
==============================================

学习目标：
- numpy：高效数值计算
- pandas DataFrame：表格数据处理（量化交易最常用）
- 读写 CSV 文件
- 数据筛选、计算、统计

量化交易关联：
- 几乎所有量化代码都用 pandas 处理行情数据
- numpy 用于数学计算（指标、统计）
- 这是整个学习路线中最重要的基础

运行前安装：
    pip install numpy pandas

运行方式：
    python 05_pandas_numpy.py
"""

import numpy as np
import pandas as pd

# ============================================
# 第一部分：numpy 基础
# ============================================

print("=" * 60)
print("第一部分：numpy - 高效数值计算")
print("=" * 60)
print()

# 1. 创建数组
prices = np.array([100, 102, 99, 105, 103, 107, 106, 110])
print(f"价格数组: {prices}")
print(f"类型: {type(prices)}")
print(f"形状: {prices.shape}")
print()

# 2. 向量化运算（比 for 循环快 100 倍）
print("=== 向量化运算 ===")

# 所有价格同时 ×1.1（涨10%）
prices_up_10 = prices * 1.1
print(f"涨10%后: {prices_up_10}")

# 计算每日收益率（不用写 for 循环！）
daily_returns = np.diff(prices) / prices[:-1] * 100  # diff 算相邻差值
print(f"每日收益率: {np.round(daily_returns, 2)}%")
print()

# 3. 常用统计函数
print("=== 统计函数 ===")
print(f"均值: {np.mean(prices):.2f}")
print(f"标准差: {np.std(prices):.2f}")     # 波动率的基础
print(f"最大值: {np.max(prices)}")
print(f"最小值: {np.min(prices)}")
print(f"累计求和: {np.cumsum(daily_returns[-3:])}")  # 最近3天累计收益
print()

# 4. 布尔索引（快速筛选）
print("=== 布尔索引 ===")
high_prices = prices[prices > 105]  # 筛选出 > 105 的价格
print(f"大于 105 的价格: {high_prices}")

positive_days = daily_returns[daily_returns > 0]
print(f"上涨日收益率: {np.round(positive_days, 2)}")
print()

# ============================================
# 第二部分：pandas 基础（重点）
# ============================================

print("=" * 60)
print("第二部分：pandas - 量化交易的瑞士军刀")
print("=" * 60)
print()

# 1. 创建 DataFrame（数据表）
print("=== 创建 DataFrame ===")

data = {
    "date":   ["2024-01-01", "2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05"],
    "open":   [100.0, 103.0, 107.0, 105.0, 108.0],
    "high":   [105.0, 108.0, 110.0, 109.0, 112.0],
    "low":    [98.0,  102.0, 104.0, 103.0, 107.0],
    "close":  [103.0, 107.0, 105.0, 108.0, 111.0],
    "volume": [1000000, 1200000, 900000, 1100000, 1500000],
}

df = pd.DataFrame(data)
df["date"] = pd.to_datetime(df["date"])  # 转换为日期类型
df = df.set_index("date")               # 将日期设为索引

print(df)
print()
print(f"形状: {df.shape} ({df.shape[0]}行 × {df.shape[1]}列)")
print(f"列名: {list(df.columns)}")
print(f"数据类型:\n{df.dtypes}")
print()

# 2. 访问数据
print("=== 访问数据 ===")
print(f"收盘价列:\n{df['close']}")
print()
print(f"第一行:\n{df.iloc[0]}")   # iloc 用数字索引
print()
print(f"前3行:\n{df.head(3)}")     # head(n) 前n行
print()

# 3. 添加计算列
print("=== 添加计算列 ===")

# 每日收益率
df["return"] = df["close"].pct_change() * 100  # pct_change() 计算百分比变化
# 累计收益率
df["cum_return"] = (1 + df["close"].pct_change()).cumprod() - 1
# 振幅
df["amplitude"] = (df["high"] - df["low"]) / df["close"] * 100

print(df[["close", "return", "cum_return", "amplitude"]].round(2))
print()

# 4. 筛选数据
print("=== 筛选数据 ===")

# 上涨的日子
up_days = df[df["return"] > 0]
print(f"上涨天数: {len(up_days)}")
print(up_days[["close", "return"]].round(2))
print()

# 成交量 > 100万 且 收盘价 > 105
filtered = df[(df["volume"] > 1000000) & (df["close"] > 105)]
print(f"放量上涨:\n{filtered[['close', 'volume']]}")
print()

# 5. 统计描述
print("=== 统计描述 ===")
print(df.describe().round(2))
print()

# 6. 移动窗口计算（量化核心操作）
print("=== 移动窗口计算 ===")

# 为了演示，用更多数据
np.random.seed(42)
dates = pd.date_range("2024-01-01", periods=30, freq="D")
close_prices = 100 + np.cumsum(np.random.randn(30) * 2)
df2 = pd.DataFrame({"close": close_prices}, index=dates)

# 移动平均线 — 量化交易最基础的指标
df2["MA5"] = df2["close"].rolling(window=5).mean()    # 5日均线
df2["MA10"] = df2["close"].rolling(window=10).mean()   # 10日均线

# 移动标准差（波动率）
df2["volatility"] = df2["close"].rolling(window=10).std()

print("最后10天数据:")
print(df2.tail(10).round(2))
print()

# 7. 生成交易信号
print("=== 用 pandas 生成交易信号 ===")

# 金叉：MA5 上穿 MA10
# 死叉：MA5 下穿 MA10
df2["signal"] = 0
df2.loc[df2["MA5"] > df2["MA10"], "signal"] = 1    # 金叉区间标记 1
df2.loc[df2["MA5"] <= df2["MA10"], "signal"] = -1   # 死叉区间标记 -1

# 找到信号变化的点（交叉点）
df2["signal_change"] = df2["signal"].diff()  # diff 找变化点

# 显示有交叉信号的日子
cross_days = df2[df2["signal_change"] != 0].dropna()
for date, row in cross_days.iterrows():
    if row["signal_change"] > 0:
        print(f"  {date.strftime('%Y-%m-%d')}: 金叉买入信号 (MA5={row['MA5']:.2f} > MA10={row['MA10']:.2f})")
    else:
        print(f"  {date.strftime('%Y-%m-%d')}: 死叉卖出信号 (MA5={row['MA5']:.2f} < MA10={row['MA10']:.2f})")

print()

# ============================================
# 8. 保存和读取 CSV
# ============================================

print("=== 保存和读取 CSV ===")

# 保存
csv_path = "sample_data.csv"
df2.to_csv(csv_path)
print(f"数据已保存到 {csv_path}")

# 读取
df_loaded = pd.read_csv(csv_path, index_col=0, parse_dates=True)
print(f"从 CSV 读取: {df_loaded.shape[0]} 行 × {df_loaded.shape[1]} 列")

# 清理临时文件
import os
os.remove(csv_path)
print(f"临时文件已清理")

print()
print("=" * 60)
print("恭喜！Python 基础课程全部完成！")
print()
print("你现在已经掌握了：")
print("  ✓ 变量和数据类型")
print("  ✓ 条件判断和循环")
print("  ✓ 函数定义和使用")
print("  ✓ 列表、字典等数据结构")
print("  ✓ pandas DataFrame 数据处理")
print("  ✓ numpy 数值计算")
print()
print("下一步：进入 01-market-data/ 学习获取真实行情数据！")
print("=" * 60)
