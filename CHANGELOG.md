# Changelog

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
