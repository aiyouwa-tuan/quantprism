# Changelog

## [2.2.0] - 2026-04-20

### 鸡哥顾问 — 金渐成投资 AI 分析模块

**New Features:**
- 鸡哥顾问页面 (`/jige`) — 基于金渐成 408 篇知识星球文章提炼的 AI 投资顾问，实时拉取股票数据，以道/势/法/术框架给出 2-3-3-2 金字塔操作建议
- 股票下拉选择器 — 预置 M7（英伟达/苹果/微软/谷歌/亚马逊/Meta/特斯拉）+ 半导体（台积电/博通/AMD/英特尔/高通/ARM）+ ETF（QQQ/SPY/SCHD/XLP）+ 防守型（伯克希尔/可口可乐/强生/宝洁/奥驰亚），每个选项含中文名称
- 408 篇文章系统提示词 — 完整 12 个心智模型（道势法术/负成本/2-3-3-2金字塔/三层账户/唐僧三问/第一兼唯一等）+ 宏观判断框架 + 6 段式结构化分析输出
- Markdown 渲染 — AI 回复自动转换为 HTML，支持加粗/列表/段落格式
- Financial Terminal 风格 UI — 价格大字显示、KPI 条、52 周高低、Beta、RSI、分析师评级

**Improvements:**
- AI 动态超时 — 根据 max_tokens 计算超时时长（`20s + tokens/100 × 4s`，最少 30s），彻底解决长文本分析超时
- DeepSeek 优先路由 — `standard` 复杂度层 DeepSeek 排第一，`AI_PROVIDER` 设置始终生效
- 默认模型切换器 — 设置页新增 4 个模型卡片（DeepSeek/ChatGPT/Claude/Gemini），实时显示配置状态，一键切换

**Bug Fixes:**
- HTMX 表单双重提交 — 移除 `<form>` 上的 `hx-post/hx-target/hx-swap` 属性，改用 `htmx.ajax()` 手动路由，解决按钮无响应问题
- `select_model()` 忽略 `AI_PROVIDER` — 修复用户设置的首选模型不生效的问题

---

## [2.1.2] - 2026-04-04

### 策略猎手过滤逻辑修复

**Fixed:**
- 策略猎手现在只展示匹配度 ≥ 40% 的策略，不再把不符合目标的候选策略凑数展示
- 当库内全部策略匹配度不足时，显示黄色警告提示用户调整目标参数，而非静默展示不相关结果
- 新增空状态文案，引导用户使用 AI 生成或调整目标

## [2.1.1] - 2026-04-04

### QA 全流程修复 — 4项用户体验 Bug 修复

**Bug Fixes:**
- ISSUE-001: 回测结果不保存到任务中心 — `/backtest/run` 完成后现在将 `BacktestRun` 写入数据库
- ISSUE-002: 「风控护盾」导航链接 404 — 修复 `base.html` 中错误的 `/risk/shield` 路由，指向 `/risk`
- ISSUE-003: 回测结果页「优化参数」等按钮无响应 — 标记为 `disabled` 并加 tooltip「即将上线」
- ISSUE-004: VIX 指标头部始终显示「--」— 添加 JS fetch 从 `/api/vix` 实时获取并渲染数值

## [2.1.0] - 2026-04-04

### AI 后台研究引擎 + 多模型支持 + UX Bug 修复

**New Features:**
- AI 后台研究引擎 (`/hunt/research/start`) — Karpathy autoresearch 循环，GitHub 种子搜索 + DeepSeek 迭代生成，后台运行不阻塞导航
- 研究进度横幅 — 切换页面后回来自动恢复进度，显示已用时长、已找到策略数、每步日志
- 多模型支持 — Settings 页新增 DeepSeek / Claude / OpenAI / Gemini / XAI API Key 管理，可选研究使用的模型
- ResearchJob & SystemConfig DB 模型 — 持久化研究任务状态与系统偏好设置

**Bug Fixes:**
- BUG-001: 策略猎手「去回测验证」跳转后策略未预选 — 新增两级模糊匹配（精确 → Token 交集），后端解析 preselect_id 传模板
- BUG-002: 回测标的固定为 SPY — 策略库新增 default_symbols 字段，按策略自动选默认标的

**Technical:**
- `strategy_hunter.py` 新增 autoresearch 引擎：Phase 0 GitHub seed + 5轮 KEEP/DISCARD 循环
- `ai_analysis.py` 新增 XAI (Grok) provider
- `models.py` 新增 ResearchJob、SystemConfig 两张表
- 修复 Python 3.9 `str | None` 类型注解兼容性问题
- 热力图三项历史修复同步：MTM 逐日盯市、y轴年份索引、equity曲线月收益

## [2.0.0] - 2026-04-02

### QuantPrism v4 — 7-Page Architecture

**Breaking Changes:**
- Complete UI restructure: 22 pages consolidated into 7
- All old routes (/, /dashboard, /strategies, /screener, etc.) now redirect to new pages

**New Pages:**
- `/goals` — 设定投资目标 (收益/回撤目标 + 系统约束推导)
- `/hunt` — 策略猎手 (策略库搜索 + AI生成 + 匹配度评分)
- `/backtest` — 回测实验室 (K线图 + 热力图 + AI建议)
- `/scan` — 标的扫描 (多策略扫描 + 仓位建议 + K线)
- `/risk` — 风控护盾 (可编辑规则 + AI对冲建议)
- `/watchlist` — 观察列表 (实时价格 + 一键跳转回测)
- `/settings` — 系统配置 (API密钥管理 + 双字段支持)

**New Features:**
- WatchlistItem model (观察列表持久化)
- UserGoals extended with asset_classes and holding_period
- Strategy parameter visualization (structured card grid)
- Click-to-edit risk rules (inline editing with save/cancel)
- Educational tooltips on all pages
- Multi-step search progress animation
- Scan range: 股票/ETF/期权 checkboxes

**Technical:**
- FastAPI + Jinja2 + HTMX + Tailwind + TradingView Charts + ECharts
- 13 old routes redirected via 301
- All existing backend modules preserved (backtester, scanner, risk_engine, etc.)
