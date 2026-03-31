# 量化交易学习路线 (Quant Trading Learning Path)

> 从零开始，系统学习量化交易，目标市场：加密货币 + 美股

---

## 学习路线总览

```
阶段0: Python基础 ──→ 阶段1: 获取数据 ──→ 阶段2: 技术指标
                                                    │
阶段5: 实盘交易 ←── 阶段4: 风险管理 ←── 阶段3: 回测框架
     (模拟盘)                                       │
                                              阶段3.5: 策略库
```

---

## 阶段详情

### 阶段 0：Python 编程基础 (`00-python-basics/`)

**目标**：掌握 Python 基本语法，能读懂和修改量化代码

| 文件 | 内容 | 关键知识点 |
|------|------|-----------|
| `01_hello_python.py` | 变量与数据类型 | 变量、字符串、数字、print |
| `02_control_flow.py` | 流程控制 | if/elif/else、for、while |
| `03_functions.py` | 函数 | 定义函数、参数、返回值 |
| `04_data_structures.py` | 数据结构 | 列表、字典、元组、集合 |
| `05_pandas_numpy.py` | 数据分析库 | pandas DataFrame、numpy 数组 |

**完成标准**：能独立写出"读取 CSV → 计算平均值 → 输出结果"的脚本

---

### 阶段 1：获取行情数据 (`01-market-data/`)

**目标**：能从交易所/数据源获取实时和历史行情数据

| 文件 | 内容 | 关键知识点 |
|------|------|-----------|
| `01_crypto_data.py` | 加密货币数据 | ccxt 库、交易所 API、OHLCV |
| `02_us_stock_data.py` | 美股数据 | yfinance 库、历史数据下载 |
| `03_data_visualization.py` | 数据可视化 | K 线图、成交量图、matplotlib |

**完成标准**：能获取 BTC 和 AAPL 的日线数据并画出 K 线图

---

### 阶段 2：技术指标 (`02-technical-indicators/`)

**目标**：理解并实现常用技术指标

| 文件 | 内容 |
|------|------|
| `01_moving_averages.py` | SMA、EMA、WMA |
| `02_rsi_macd.py` | RSI 相对强弱指数、MACD |
| `03_bollinger_bands.py` | 布林带 |
| `04_custom_indicators.py` | 自定义指标编写 |

---

### 阶段 3：回测框架 (`03-backtesting/`)

**目标**：能用历史数据验证策略是否有效

| 文件 | 内容 |
|------|------|
| `01_simple_backtest.py` | 手写简单回测引擎（理解原理） |
| `02_backtest_framework.py` | 使用 vectorbt 回测框架 |
| `03_performance_metrics.py` | 夏普比率、最大回撤、胜率等 |
| `04_optimization.py` | 策略参数优化 |

---

### 阶段 4：经典策略 (`04-strategies/`)

**目标**：实现并回测经典量化策略

| 文件 | 策略 | 原理 |
|------|------|------|
| `01_dual_ma_cross.py` | 双均线交叉 | 短期均线上穿长期均线买入 |
| `02_rsi_strategy.py` | RSI 超买超卖 | RSI < 30 买入，> 70 卖出 |
| `03_breakout.py` | 突破策略 | 价格突破 N 日高点买入 |
| `04_mean_reversion.py` | 均值回归 | 偏离均值后回归 |
| `05_momentum.py` | 动量策略 | 追涨杀跌的系统化版本 |

---

### 阶段 5：风险管理 (`05-risk-management/`)

**目标**：学会控制风险，不因一次交易亏光

| 文件 | 内容 |
|------|------|
| `01_position_sizing.py` | 固定比例、Kelly 公式 |
| `02_stop_loss.py` | 固定止损、移动止损、ATR 止损 |
| `03_portfolio.py` | 多策略/多品种分散 |

---

### 阶段 6：实盘交易 (`06-live-trading/`)

**目标**：先模拟盘验证，再小资金实盘

| 文件 | 内容 |
|------|------|
| `01_crypto_paper_trade.py` | 加密货币模拟盘（ccxt testnet） |
| `02_us_stock_paper_trade.py` | 美股模拟盘（Alpaca paper） |
| `03_monitoring.py` | 实盘监控与异常告警 |

---

## 环境搭建

```bash
# 1. 安装 Python（推荐 3.10+）
# macOS 自带 python3，或用 Homebrew 安装：
brew install python

# 2. 创建虚拟环境（推荐）
cd /Volumes/MaiTuan2T/Quant
python3 -m venv venv
source venv/bin/activate

# 3. 安装依赖
pip install -r requirements.txt
```

---

## 学习建议

1. **按顺序学**：每个阶段都依赖前一个阶段的知识
2. **动手运行**：每个 .py 文件都可以直接运行，先跑一遍看结果，再读代码
3. **修改实验**：改参数、换标的、调策略，观察结果变化
4. **做笔记**：在 `docs/` 目录下记录你的学习心得
5. **不要急于实盘**：至少完成到阶段 5 并且模拟盘跑了 1 个月再考虑实盘
