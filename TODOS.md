# TODOS

## Phase 2: "Goal-Driven" 策略匹配机制
**What:** 设计系统如何根据用户的收益/回撤目标自动筛选和推荐匹配的策略，而不只是输出一个持仓上限数字。
**Why:** 外部审查指出 Phase 1 的约束推导只产出 max_positions，到 Phase 2 策略选择仍是手动的。如果不解决，"目标驱动"的核心差异化就名存实亡。
**Pros:** 让 "Goal-Driven" 从营销语言变成真实的产品机制。
**Cons:** 需要定义"策略兼容性"的评判标准（回测 Sharpe? 最大回撤? 胜率?），增加 Phase 2 设计复杂度。
**Context:** Phase 1 的 `derive_constraints()` 产出 max_positions 和 max_position_pct。Phase 2 需要一个机制：给定这些约束 + 用户目标，从策略模板库中筛选出兼容的策略并排序。可能的实现：回测每个策略 → 检查历史回撤是否在目标内 → 排除不兼容的 → 按 Sharpe 排序推荐。
**Depends on:** Phase 2 策略模板系统完成。
**Added:** 2026-03-31 (eng review outside voice finding #7)

## Phase 1.5: 数据采集策略定义
**What:** 定义从 Phase 1.5 开始需要持续采集什么市场数据、以什么频率、存储在哪里，为 Phase 5 跨市场关联分析做数据准备。
**Why:** Phase 5 说"需要 3 个月数据"但没有定义采集方案。如果 Phase 1.5 不开始采集，Phase 5 永远没有数据可用。
**Pros:** 3 个月后自动有足够数据做关联分析，不需要事后补数据。
**Cons:** 增加 Phase 1.5 的设计范围。
**Context:** 需要决定：采集哪些品种（SPY, BTC, ETH 等）、什么频率（日线够用 vs 小时线）、存 SQLite 还是 CSV、数据量估算（1 年日线约 250 行/品种，可控）。yfinance 可免费获取历史数据，但实时数据有限制。
**Depends on:** Phase 1.5 券商 API 接入。
**Added:** 2026-03-31 (eng review outside voice finding #8)
