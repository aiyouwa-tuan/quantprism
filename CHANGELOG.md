# Changelog

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
