# TODOS

> 优先级：P1 = 本周 / P2 = 本月 / P3 = 未来版本

---

## [v1.0 · P1] Paper Trading — dry_run 模式

**What:** 在 `broker.py` 加一个 `DRY_RUN` 环境变量开关。开启后所有下单请求拦截到本地模拟撮合器，用实时价格计算假设成交，账户余额保存在 `paper_positions` 表，不触碰真实资金。

**Why:** 策略上线前必须先跑模拟盘验证。现在执行引擎能生成信号，但没有"安全沙盒"追踪如果你全部确认了会发生什么。没有 dry_run，策略验证只能靠回测历史数据，无法验证实时行为。受 Freqtrade `dry_run` 模式设计启发。

**Pros:**
- 新策略从 dry_run 毕业再进实盘，降低试错成本
- 可对比 dry_run PnL vs 实盘 PnL，量化"执行摩擦"
- 实现简单，不涉及任何新外部依赖

**Cons:** 需新增 `paper_positions` 表 + 模拟撮合逻辑（约 80 行代码）

**实现要点:**
```python
# broker.py
DRY_RUN = os.getenv("DRY_RUN", "false").lower() == "true"

def submit_order(symbol, qty, side, ...):
    if DRY_RUN:
        return simulate_fill(symbol, qty, side)  # 写入 paper_positions 表
    return real_alpaca_api.submit(...)
```
新增 `paper_positions` 表（与 `Position` 结构相同，加 `is_paper=True` 字段）。UI 上 dry_run 状态需有明显标识（红/绿 badge）。

**Effort:** S（人工半天 / CC+gstack ~1小时）
**Priority:** P1 — 今天可以开始，无外部依赖
**Depends on:** 无
**归属版本:** v1.0

---

## [v1.0 · P1] Goal-Driven Parameter Optimizer（Hyperopt 风格）

**What:** 自动参数优化循环。给定用户目标（最大回撤 10%，目标收益 15%），对每个策略的参数空间做 Grid Search，找出历史上满足风控目标同时最大化 Sharpe 的参数组合，自动写回 `StrategyConfig.params_yaml`。

**Why:** 这是 "Phase 2 Goal-Driven 策略匹配机制"（见下）的核心实现。现在 `params_yaml` 是手动填写的静态配置，没有这个优化器，"目标驱动"就是口号不是产品机制。受 Freqtrade Hyperopt 的 loss function 设计启发：不满足回撤目标直接淘汰，满足目标的按 Sharpe 排序。

**Pros:**
- "Goal-Driven"从 UI 标签变成真实的参数推导引擎
- `backtester.py` 已有完整回测逻辑，只差外层优化循环
- 用户只需设目标，系统自动找最优参数

**Cons:** Grid Search 在参数空间大时耗时；需要限制搜索空间防止超时（每个策略建议最多 200 次组合）

**实现要点:**
```python
# 新文件 app/optimizer.py
def goal_driven_loss(metrics: BacktestMetrics, goals: UserGoals) -> float:
    if metrics.max_drawdown > goals.max_drawdown:
        return 999.0   # 不满足风控，直接淘汰
    return -metrics.sharpe_ratio  # 目标：最小化负 Sharpe

def optimize_strategy(strategy_name, goals, param_grid) -> dict:
    best_params, best_loss = None, 999.0
    for params in expand_grid(param_grid):
        metrics = run_backtest(strategy_name, params)
        loss = goal_driven_loss(metrics, goals)
        if loss < best_loss:
            best_loss, best_params = loss, params
    return best_params
```
新增 API 端点 `POST /strategies/{id}/optimize`，结果自动更新 `StrategyConfig.params_yaml`。

**Effort:** M（人工 1-2 天 / CC+gstack ~2小时）
**Priority:** P1
**Depends on:** dry_run 完成后最有价值，但可独立实现
**归属版本:** v1.0

---

## [v1.0 · P1] Regime-Aware Execution Pipeline（执行管线感知市场环境）

**What:** 执行流程加入显式的 regime 过滤层。在 `generate_pending_signals()` 之后、`submit_order()` 之前，检查当前市场 regime 和策略的 regime 适配性。高波环境下只允许适合高波的策略生成信号；危机 regime 下可选择全部暂停。

**Why:** 现在 `risk_engine.py` 有 `detect_market_regime()`，`execution.py` 有信号生成，但两者没有连接。Regime 检测结果不影响执行决策，导致熊市/高波时动量策略仍然生成买入信号，用户必须手动判断要不要忽略。受 QuantConnect LEAN Framework 的 Alpha→Portfolio→Risk→Execution 管线架构启发。

**Pros:**
- 自动过滤"在错误市场环境下出现的正确信号"
- Risk Engine 的 regime 检测终于有实际用处
- 减少用户手动判断负担

**Cons:** 需给每个策略添加 `compatible_regimes` 属性；初期可以用默认值（所有策略兼容所有 regime）

**实现要点:**
```python
# execution.py — generate_pending_signals() 内部新增过滤逻辑
regime = detect_market_regime()           # 已有
risk = compute_portfolio_risk(db)         # 已有

for config in active_strategies:
    if not strategy_compatible_with_regime(config, regime):
        continue  # ← 新增
    if risk["drawdown_headroom"] < MIN_HEADROOM:
        continue  # ← 新增：组合接近风控上限，暂停开新仓
    # 原有信号生成逻辑不变...
```
`StrategyConfig` 模型新增 `compatible_regimes` 字段（JSON 列表，默认 `["low", "medium", "high"]`）。

**Effort:** S（人工半天 / CC+gstack ~1小时）
**Priority:** P1
**Depends on:** 无，独立可实现
**归属版本:** v1.0

---

## [v1.5 · P2] Strategy Performance Analyzer by Regime（按市场环境分解策略表现）

**What:** 回测结果不只输出总体 Sharpe/最大回撤，还按市场 regime 分类：同一策略在牛市/熊市/震荡/高波期间分别的 Sharpe、胜率、平均持仓时间。结果存入 `strategy_performance` 表，策略管理页面展示 regime 适配热力图。

**Why:** 受 Backtrader Analyzer 模式启发。现在回测输出是单一指标，无法回答"这个策略适合什么市场"。这是 CEO Review Expansion #4（策略表现排行榜）的完整实现，也是 Regime-Aware Pipeline 的数据来源——有了这个分析器，系统才能自动配置每个策略的 `compatible_regimes` 标签。

**Pros:**
- 回测从"历史总收益"进化为"在你实际交易条件下的表现分解"
- 自动生成 regime 适配标签，驱动 v1.0 执行管线的过滤逻辑
- 帮助用户理解"为什么这个策略最近失效了"

**Cons:** 需在回测时标记每根 K 线的 regime，增加回测数据处理量；VIX 历史数据需额外拉取

**实现要点:**
新增 `strategy_performance` 表：
```sql
strategy_config_id, regime, period_start, period_end,
sharpe, win_rate, max_drawdown, avg_holding_days, trade_count
```
VIX regime 分类：`< 15` = 低波牛市，`15-20` = 正常，`20-30` = 高波，`> 30` = 危机。
每次回测结束后按 regime 分组统计写表，策略管理页面展示热力图。

**Effort:** M（人工 1-2 天 / CC+gstack ~2小时）
**Priority:** P2
**Depends on:** Regime-Aware Pipeline (v1.0) 完成后数据更有价值
**归属版本:** v1.5

---

## [v2.0 · P3] Phase 2: "Goal-Driven" 策略匹配机制

**What:** 设计系统如何根据用户的收益/回撤目标自动筛选和推荐匹配的策略，而不只是输出一个持仓上限数字。
**Why:** 外部审查指出 Phase 1 的约束推导只产出 max_positions，到 Phase 2 策略选择仍是手动的。如果不解决，"目标驱动"的核心差异化就名存实亡。
**Pros:** 让 "Goal-Driven" 从营销语言变成真实的产品机制。
**Cons:** 需要定义"策略兼容性"的评判标准（回测 Sharpe? 最大回撤? 胜率?），增加 Phase 2 设计复杂度。
**Context:** Phase 1 的 `derive_constraints()` 产出 max_positions 和 max_position_pct。Phase 2 需要一个机制：给定这些约束 + 用户目标，从策略模板库中筛选出兼容的策略并排序。可能的实现：回测每个策略 → 检查历史回撤是否在目标内 → 排除不兼容的 → 按 Sharpe 排序推荐。注：[v1.0] Goal-Driven Parameter Optimizer 是这个功能的前置实现，完成后本条目可标记为已解决。
**Depends on:** [v1.0] Parameter Optimizer 完成。
**Added:** 2026-03-31 (eng review outside voice finding #7)

---

## [v2.0 · P3] Phase 1.5: 数据采集策略定义

**What:** 定义从 Phase 1.5 开始需要持续采集什么市场数据、以什么频率、存储在哪里，为 Phase 5 跨市场关联分析做数据准备。
**Why:** Phase 5 说"需要 3 个月数据"但没有定义采集方案。如果 Phase 1.5 不开始采集，Phase 5 永远没有数据可用。
**Pros:** 3 个月后自动有足够数据做关联分析，不需要事后补数据。
**Cons:** 增加 Phase 1.5 的设计范围。
**Context:** 需要决定：采集哪些品种（SPY, BTC, ETH 等）、什么频率（日线够用 vs 小时线）、存 SQLite 还是 CSV、数据量估算（1 年日线约 250 行/品种，可控）。yfinance 可免费获取历史数据，但实时数据有限制。
**Depends on:** Phase 1.5 券商 API 接入。
**Added:** 2026-03-31 (eng review outside voice finding #8)
