# Goal-Driven Trading OS — 产品路线图

**最后更新：** 2026-04-02
**当前版本：** v0.9（工具箱阶段）

---

## 版本总览

| 版本 | 代号 | 核心目标 | 状态 |
|------|------|---------|------|
| **v0.9** | 工具箱 | 仓位计算 + 持仓记录 + IBKR 实时数据 + 策略库 + 回测 + 机会引擎 + AI 研究 | ✅ 已发布 |
| **v1.0** | Goal-Driven Engine | 三大机制：dry_run 模拟盘 + 参数优化器 + Regime 感知执行管线 | 🔨 开发中 |
| **v1.5** | Alpha Discovery | 按市场环境分解策略表现 + 交易日志分析 + 个人 Alpha 发现 | 📋 规划中 |
| **v2.0** | Multi-Market | 加密货币多市场 + 跨市场关联风险 + 自动执行 | 📋 未来 |

详细任务见 `TODOS.md`。

---

## v0.9 "工具箱"（已完成）

已实现功能：

- **仓位计算器**：根据账户金额/入场价/止损价计算合理仓位
- **目标设定**：设定年收益目标 + 最大回撤，系统推导持仓上限约束
- **持仓记录**：手动记录开仓/平仓，追踪未实现盈亏
- **交易日志**：记录每笔交易的进场原因、市场状态、情绪状态
- **IBKR 实时数据**：Interactive Brokers 实盘数据接入
- **策略库**：SMA 交叉、RSI 动量、布林带均值回归
- **回测引擎 v2**：Walk-Forward 验证 + 危机压力测试（2008/2020/2022）+ 滑点佣金模型
- **机会引擎**：多策略并行扫描，筛选符合条件的交易机会
- **AI 策略研究**：Claude API 驱动的策略发现和研究管线
- **策略发现库**：可浏览的策略模板库，支持 AI 深度分析
- **风险仪表盘**：组合风险实时监控，Regime 检测
- **告警系统**：飞书 Webhook + Twilio SMS 双渠道推送

---

## v1.0 "Goal-Driven Engine"（开发中）

**目标：** 把现有孤立模块串联成真正的目标驱动引擎。三个机制都是对现有代码的"连接"，不是从零重建。

### 功能 1：dry_run 模拟交易模式

**灵感来源：** Freqtrade `dry_run` 模式

**是什么：** `broker.py` 加一个 `DRY_RUN` 环境变量开关。开启后所有下单拦截到本地模拟撮合器，用真实价格计算假设成交，账户余额和持仓保存在 `paper_positions` 表，不触碰真实资金。

**为什么先做这个：** 策略验证的安全沙盒。回测验证了历史数据，模拟盘验证实时行为。没有 dry_run，策略从回测到实盘是盲跳。

**涉及文件：** `broker.py`、`models.py`（新增 `paper_positions` 表）、执行页面 UI（新增 dry_run badge）

**完成标准：** `.env` 里 `DRY_RUN=true` 后，执行信号不发往 Alpaca，持仓记录在 `paper_positions` 表；UI 有明显的"模拟盘"标识。

---

### 功能 2：Goal-Driven Parameter Optimizer

**灵感来源：** Freqtrade Hyperopt

**是什么：** 新增 `app/optimizer.py`。给定用户目标（最大回撤 10%，目标收益 15%），对每个策略的参数空间做 Grid Search，找出满足风控目标同时 Sharpe 最高的参数组合，自动写回 `StrategyConfig.params_yaml`。

**核心逻辑：**
```
loss function:
  - 如果历史最大回撤 > 用户目标 → 淘汰（loss = 999）
  - 否则 → loss = -Sharpe（目标：Sharpe 越高越好）

搜索：
  for each param combination in param_grid:
      run backtest → compute loss → keep best
```

**为什么这是核心：** 现在 `params_yaml` 是手动填写的静态值。这个优化器让"目标驱动"从界面标签变成真实的参数推导机制。

**新增 API：** `POST /strategies/{id}/optimize` → 结果直接更新策略配置

**涉及文件：** 新增 `app/optimizer.py`、`main.py`（新增路由）、策略管理页面（新增"优化"按钮）

**完成标准：** 点击"优化"后系统自动搜索参数，找到满足用户回撤目标的最优 Sharpe 参数并保存；页面显示优化前后的指标对比。

---

### 功能 3：Regime-Aware Execution Pipeline

**灵感来源：** QuantConnect LEAN Framework Alpha→Portfolio→Risk→Execution 管线

**是什么：** 在 `generate_pending_signals()` 执行流中加入显式过滤层。利用已有的 `detect_market_regime()` 和 `compute_portfolio_risk()` 两个函数，在信号生成后、用户确认前过滤掉"不适合当前市场状态"的信号。

**执行流变化：**
```
v0.9 流程：                    v1.0 流程：
生成信号                        生成信号
    ↓                               ↓
人工确认              →         Regime 过滤（利用已有 detect_market_regime）
    ↓                               ↓
下单                            风险余量检查（利用已有 compute_portfolio_risk）
                                    ↓
                                人工确认
                                    ↓
                                dry_run / 实盘（由功能 1 的开关决定）
```

**数据模型变化：** `StrategyConfig` 新增 `compatible_regimes` 字段（JSON 列表，默认 `["low","medium","high"]`，危机 regime 下暂停需用户主动配置）

**涉及文件：** `execution.py`、`models.py`（新增字段）、策略配置页面（新增 regime 选择）

**完成标准：** VIX > 30（危机 regime）时，被标记为"不适合危机"的策略不生成信号；组合回撤余量 < 2% 时，所有新开仓信号暂停。

---

## v1.5 "Alpha Discovery"（规划中）

### 功能 4：Strategy Performance Analyzer by Regime

**灵感来源：** Backtrader Analyzer 模式

**是什么：** 回测结果不只输出总体 Sharpe，还按市场 regime 分类输出四象限表现。新增 `strategy_performance` 表存储分类结果，策略管理页面展示 regime 热力图。

**VIX Regime 分类标准：**
| Regime | VIX 范围 | 市场特征 |
|--------|---------|---------|
| 低波牛市 | < 15 | 趋势明显，动量策略有效 |
| 正常 | 15–20 | 均值回归和动量均可 |
| 高波 | 20–30 | 均值回归有效，动量慎用 |
| 危机 | > 30 | 大多数策略失效，减仓优先 |

**新增数据表：**
```sql
strategy_performance:
  strategy_config_id, regime, period_start, period_end,
  sharpe, win_rate, max_drawdown, avg_holding_days, trade_count
```

**与 v1.0 的连接：** 这个分析器的输出是 Regime-Aware Pipeline（v1.0 功能 3）的数据来源。分析器跑完后，系统可以自动建议每个策略的 `compatible_regimes` 配置。

### 其他 v1.5 功能（来自 CEO Review Expansion）

- **交易决策日志分析**：3 个月后生成"个人交易模式分析"，找出你在哪种条件下胜率最高（Expansion #1）
- **执行偏差追踪**：对比策略信号建议 vs 实际操作，量化情绪决策的成本（Expansion #2）

---

## v2.0 "Multi-Market"（未来）

- 加密货币多市场完整接入（Phase 3）
- 跨市场关联风险（BTC 下跌时美股科技股的联动）
- 自动执行（基于 dry_run 验证通过的策略，人工确认降级为可选）
- 飞书 + 短信双渠道告警（Expansion #3）

**产品化触发条件（不是时间驱动，是里程碑驱动）：**
- 自用 3 个月以上
- 有明确的"这个功能救了我一笔钱"的案例
- 有至少 5 个人主动问"你用的什么工具"

---

## 设计原则

1. **自用优先**：先让自己真正用起来，再考虑产品化
2. **风险优先**：任何新功能上线前，先通过 dry_run 验证
3. **不要借鉴的部分**：QuantConnect 云基础设施（过重）、NautilusTrader Rust 引擎（日线级别不需要微秒延迟）、Hummingbot 做市策略（不同使用场景）
