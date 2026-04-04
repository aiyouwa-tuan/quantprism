# QuantPrism — Design Handoff Spec v1.0

**版本**: 1.0
**日期**: 2026-04-04
**作者**: Claude Code (design-handoff skill)
**状态**: 待确认 (Pending User Review)

---

## 设计令牌（Design Tokens）

> 以下令牌从现有模板提取，所有新组件必须使用这些值，禁止使用硬编码色值。

### 颜色令牌

| 令牌名 | 值 | 用途 |
|--------|-----|------|
| `color-bg-900` | `#0a0e1a` | 全局最深背景 |
| `color-bg-800` | `#111827` | 导航栏背景、次级背景 |
| `color-bg-700` | `#1a2035` | 卡片背景（主要） |
| `color-bg-600` | `#232b3e` | 卡片边框、网格线 |
| `color-bg-500` | `#2d3650` | 导航激活态背景 |
| `color-accent-green` | `#22c55e` | 正收益、买入信号、成功态 |
| `color-accent-red` | `#ef4444` | 负收益、卖出信号、警告态 |
| `color-accent-blue` | `#3b82f6` | 主操作按钮、链接、激活标签 |
| `color-accent-yellow` | `#eab308` | 警告、SMA20指标线、中性信号 |
| `color-accent-purple` | `#8b5cf6` | Logo渐变副色、期权标记 |
| `color-text-primary` | `#ffffff` | 主要文字 |
| `color-text-secondary` | `#9ca3af` | 辅助标签、坐标轴文字 |
| `color-text-muted` | `#6b7280` | 禁用态、占位符 |
| `color-logo-gradient` | `linear-gradient(135deg, #3b82f6, #8b5cf6)` | Logo、品牌强调 |

### 字体令牌

| 令牌名 | 值 | 用途 |
|--------|-----|------|
| `font-size-hero` | `48px / font-bold` | Hero BNV 数字 |
| `font-size-kpi` | `20-24px / font-bold` | 指标卡主数值 |
| `font-size-label` | `11-12px / font-normal` | 指标标签、坐标轴 |
| `font-size-body` | `14px / font-normal` | 正文、表格内容 |
| `font-size-caption` | `10-11px / font-normal` | 角标、badge |
| `font-mono` | `monospace` | K线数据栏、价格显示 |

### 间距令牌

| 令牌名 | 值 | 用途 |
|--------|-----|------|
| `spacing-card-pad` | `20px (p-5)` | 卡片内边距 |
| `spacing-card-gap` | `16px (gap-4)` | 卡片间距 |
| `spacing-section-gap` | `16px (mb-4)` | 区块间距 |
| `spacing-nav-width` | `192px (w-48)` | 侧边导航宽度 |
| `radius-card` | `12px (rounded-xl)` | 卡片圆角 |
| `radius-pill` | `999px (rounded-full)` | 标签、pill 按钮 |

### 图表颜色令牌（ECharts/LightweightCharts）

| 元素 | 颜色 |
|------|------|
| 图表背景 | `transparent` |
| 网格线 | `#232b3e` |
| 坐标轴线 | `#232b3e` |
| 坐标轴文字 | `#9ca3af` |
| 上涨 K线 | `#22c55e` |
| 下跌 K线 | `#ef4444` |
| SMA20 | `#eab308` |
| 权益曲线 | `#3b82f6` |
| 回撤填充 | `rgba(239, 68, 68, 0.15)` |
| VisualMap 渐变 | `['#ef4444', '#1a2035', '#22c55e']` |

---

## Feature 1: UI 全局动画系统

### 1.1 新建文件: `app/static/qp-animations.css`

#### @keyframes 规范

```
fadeInUp:
  from: { opacity: 0; transform: translateY(20px); }
  to:   { opacity: 1; transform: translateY(0); }
  duration: 0.45s
  easing: cubic-bezier(0.16, 1, 0.3, 1)

shimmer:
  from: { background-position: -200% center; }
  to:   { background-position: 200% center; }
  duration: 1.5s
  easing: linear
  iteration: infinite

pulseGlow:
  0%:   { box-shadow: 0 0 0 0 rgba(59,130,246,0.4); }
  70%:  { box-shadow: 0 0 0 8px rgba(59,130,246,0); }
  100%: { box-shadow: 0 0 0 0 rgba(59,130,246,0); }
  duration: 2s
  iteration: infinite
```

#### 组件样式规范

**`.qp-card`** (玻璃拟态卡片)
```css
background: rgba(26, 32, 53, 0.85);        /* color-bg-700 + alpha */
backdrop-filter: blur(12px);
border: 1px solid rgba(59, 130, 246, 0.15); /* 蓝色微发光边框 */
border-radius: 12px;
transition: transform 0.2s ease, box-shadow 0.2s ease, border-color 0.2s ease;

/* hover 状态 */
:hover {
  transform: translateY(-2px);
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.4);
  border-color: rgba(59, 130, 246, 0.35);
}
```

**`.qp-card-enter`** (错开入场动画)
```css
animation: fadeInUp 0.45s cubic-bezier(0.16, 1, 0.3, 1) both;

/* nth-child 延迟规则 */
&:nth-child(1)  { animation-delay: 0.00s; }
&:nth-child(2)  { animation-delay: 0.06s; }
&:nth-child(3)  { animation-delay: 0.12s; }
&:nth-child(4)  { animation-delay: 0.18s; }
&:nth-child(5)  { animation-delay: 0.24s; }
&:nth-child(n+6){ animation-delay: 0.30s; } /* 超过5个统一延迟 */
```

**`.qp-skeleton`** (骨架屏)
```css
background: linear-gradient(90deg,
  #1a2035 25%,         /* color-bg-700 */
  #232b3e 50%,         /* color-bg-600 */
  #1a2035 75%
);
background-size: 400% 100%;
animation: shimmer 1.5s linear infinite;
border-radius: 6px;
```

**`.qp-number-up`** (数字滚动宿主)
```css
display: inline-block;
font-variant-numeric: tabular-nums;
/* 实际滚动由 qp-core.js 的 initCountUp() 驱动 */
```

**`.qp-gradient-border`** (彩虹渐变边框)
```css
position: relative;
&::before {
  content: '';
  position: absolute; inset: -1px;
  border-radius: inherit;
  background: linear-gradient(135deg, #3b82f6, #8b5cf6, #22c55e);
  z-index: -1;
}
```

**`.qp-pulse-glow`** (脉冲光晕，用于实时数据点)
```css
animation: pulseGlow 2s ease-out infinite;
```

---

### 1.2 新建文件: `app/static/qp-core.js`

#### `initCountUp(el, target, duration=800)` 函数规范
- 输入：DOM元素、目标数值（支持负数）、动画时长(ms)
- 行为：从 0 → target，easeOut 缓动，使用 `requestAnimationFrame`
- 格式化：自动检测 `data-format` 属性：
  - `data-format="percent"` → 保留1位小数 + `%`
  - `data-format="currency"` → 千分位 + `$`
  - `data-format="ratio"` → 保留2位小数
  - 无属性 → 整数

#### `initCardStagger(container)` 函数规范
- 输入：父容器 DOM 元素
- 行为：遍历所有直接子元素，添加 `.qp-card-enter` + 计算 `animation-delay`
- 调用时机：`DOMContentLoaded` + HTMX `htmx:afterSwap` 事件

#### MutationObserver 规范
- 监听 `body`，`subtree: true, childList: true`
- 新增节点时，对含 `.qp-number-up` 的元素调用 `initCountUp`
- 对含 `.qp-card-enter` 的父容器调用 `initCardStagger`

#### `showSkeleton(containerId)` / `hideSkeleton(containerId)` 规范
- `showSkeleton`: 将容器内容替换为对应数量的 `.qp-skeleton` 占位块
- `hideSkeleton`: 移除占位块（HTMX swap 自动覆盖，通常无需手动调用）
- HTMX 集成：`hx-on:htmx:before-request="showSkeleton(this.id)"`

---

## Feature 2: 导航栏重构

### 当前状态
- 单列平铺 7 个导航项
- 无分组、无层级

### 目标状态

```
┌──────────────────────────┐
│  [Logo] QuantPrism       │  h-14, border-b border-dark-600
├──────────────────────────┤
│  📊 概览                  │  导航项（激活: bg-dark-500）
├─ · · · · · · · · · · ·  ┤  分组分隔线: border-t border-dark-600/50, mt-2 pt-2
│  STRATEGY WORKSHOP       │  分组标签: text-[10px] text-gray-600 uppercase tracking-widest px-3 py-1
│    🧪 策略猎手             │  子项: pl-5（额外缩进8px）
│    ⚗️  回测实验室          │  带展开箭头 ▾
│       └─ 单次回测         │  二级子项: pl-8，仅展开时显示
│       └─ 平行时空         │
│       └─ 策略对比         │
│    📋 任务中心             │  子项
├─ · · · · · · · · · · ·  ┤
│  MARKET SCAN             │  分组标签
│    🔍 标的扫描             │
│    🌐 宏观经济             │
├─ · · · · · · · · · · ·  ┤
│  TRADE MANAGEMENT        │  分组标签
│    💼 当前持仓             │
│    👁  观察列表            │
│    🛡️  风控护盾            │
├─ · · · · · · · · · · ·  ┤
│  SYSTEM                  │  分组标签
│    ⚙️  设定目标            │
└──────────────────────────┘
```

### 尺寸与样式规范

| 元素 | 样式 |
|------|------|
| 导航容器 | `w-48 h-screen fixed left-0 top-0 bg-dark-800 border-r border-dark-600 flex flex-col` |
| Logo区 | `h-14 px-4 flex items-center border-b border-dark-600` |
| 分组标签 | `text-[10px] text-gray-600 uppercase tracking-widest px-3 mt-3 mb-1` |
| 导航项（一级） | `flex items-center gap-2.5 px-3 py-2 text-sm rounded-lg mx-2 transition` |
| 导航项（二级） | `flex items-center gap-2 pl-8 pr-3 py-1.5 text-xs rounded-lg mx-2 transition` |
| 激活态 | `bg-dark-500 text-white` |
| 非激活态 | `text-gray-400 hover:text-white hover:bg-dark-700` |
| 图标 | `w-4 h-4 opacity-70`（激活时 `opacity-100`） |
| 展开箭头 | `ml-auto text-gray-600 transition-transform`（展开时 `rotate-180`） |
| 分组分隔线 | `border-t border-dark-600/40 mx-3 my-1` |

### 交互规范

| 触发 | 行为 |
|------|------|
| 点击有子项的导航项 | 展开/收起二级菜单（`max-height` 动画，0 → auto，0.25s ease） |
| 点击二级菜单项 | 跳转路由 + 高亮该项 + 父项保持展开 |
| 当前路由匹配 | 对应项自动激活 + 父组展开 |
| 侧边栏宽度 | 固定 `w-48`，不可收起（当前MVP） |

---

## Feature 3: 回测实验室 — 8-Tab 结构

### 总体布局

```
qp_backtest.html
├── 参数面板 (顶部，常驻)
│   ├── 标的输入
│   ├── 日期范围
│   ├── 策略选择
│   └── [运行回测] 按钮
│
├── Tab 导航栏
│   Tab 1: 总览   Tab 2: 权益曲线   Tab 3: 收益分布
│   Tab 4: 标的分析   Tab 5: 逐笔分析   Tab 6: 滚动指标
│   Tab 7: 高阶统计 [Phase 2]   Tab 8: 平行时空
│
└── Tab 内容区 (HTMX swap)
    └── backtest_inline.html (重构后支持8 Tab)
```

### Tab 导航栏规范

```
样式容器: flex gap-0 border-b border-dark-600 mb-4

Tab 按钮（激活）:
  px-4 py-3 text-sm font-medium text-white
  border-b-2 border-accent-blue
  background: transparent

Tab 按钮（非激活）:
  px-4 py-3 text-sm text-gray-500
  hover: text-gray-300
  border-b-2 border-transparent
  transition: 0.15s

Phase 2 标签:
  右上角 badge: "Phase 2"
  text-[9px] bg-accent-purple/20 text-accent-purple px-1 rounded
  position: relative, top: -2px
```

### 交互规范（ECharts 懒加载）

```javascript
// 进入 Tab 时才初始化图表（防止 0px canvas 错误）
const tabState = {};

function activateTab(tabId) {
  if (!tabState[tabId]) {
    tabState[tabId] = true;
    initChartForTab(tabId);  // 只在第一次进入时初始化
  }
  // 已初始化：调用 chart.resize() 即可
  chartInstances[tabId]?.resize();
}
```

---

### Tab 1: 总览指标

#### 布局结构
```
┌─────────────────────────────────────────────────┐
│ [Goal Badge] 达到目标 ✓  or  未达标 ✗           │  条件渲染
├──────┬──────┬──────┬──────┬──────┬──────┬──────┤
│总收益│年化率│最大回│Sharpe│Sortino│胜率 │交易数│  7列指标卡
├──────┴──────┴──────┴──────┴──────┴──────┴──────┤
│Calmar │ SQN │最佳单│最差单│均收益│持仓天│盈亏比│  第2行6-7列
├─────────────────────────────────────────────────┤
│  AI 建议区块（蓝色边框）                         │
└─────────────────────────────────────────────────┘
```

#### 指标卡规范

```
容器: bg-dark-800 rounded-lg p-3 text-center
       animation: qp-card-enter（第n个延迟n*60ms）

标签: text-xs text-gray-500 mb-1
数值: text-xl font-bold + qp-number-up
      正收益 → text-accent-green
      负收益 → text-accent-red
      中性（Sharpe等）→ text-white

SQN 评级 badge（数值右侧）:
  <1.6  → text-[10px] bg-red-500/20 text-red-400 px-1 rounded
  2.0+  → text-[10px] bg-green-500/20 text-green-400 px-1 rounded
  3.0+  → text-[10px] bg-purple-500/20 text-purple-400 px-1 rounded
  文字：差 / 良 / 优 / 卓越
```

#### AI 建议区块（无变化，保留现有）

```
容器: bg-accent-blue/10 border border-accent-blue/30 rounded-xl p-5 mb-4
标题: text-sm font-semibold text-white
正文: text-sm text-gray-300 leading-relaxed
按钮组: bg-dark-600 text-gray-300 px-4 py-2 rounded-lg text-sm
```

---

### Tab 2: 权益曲线

#### 布局
```
┌─────────────────────────────────────────────────┐
│ 权益曲线（LightweightCharts）       高度: 300px  │
├─────────────────────────────────────────────────┤
│ 回撤曲线（ECharts area, 红色填充）  高度: 120px  │
├─────────────────────────────────────────────────┤
│ K线图（现有）                       高度: 500px  │
└─────────────────────────────────────────────────┘
```

#### 权益曲线 LightweightCharts 配置
```javascript
chart config:
  layout: { background: { color: 'transparent' }, textColor: '#9ca3af' }
  grid: { vertLines/horzLines: { color: '#232b3e' } }
  height: 300

areaSeries:
  topColor: 'rgba(59, 130, 246, 0.3)'   // accent-blue alpha
  bottomColor: 'rgba(59, 130, 246, 0)'
  lineColor: '#3b82f6'
  lineWidth: 2
```

#### 回撤曲线 ECharts 配置
```javascript
series: [{
  type: 'line',
  areaStyle: { color: 'rgba(239, 68, 68, 0.15)' },
  lineStyle: { color: '#ef4444', width: 1 },
  itemStyle: { color: '#ef4444' }
}]
yAxis: { max: 0, axisLabel: { formatter: '{value}%' } }
height: '120px'
```

---

### Tab 3: 收益分布

#### 布局
```
┌──────────────────────┬──────────────────────────┐
│ 收益分布直方图        │  偏度/峰度统计表         │
│ (ECharts bar)        │  4行 × 2列               │
│ 高度: 300px          │  bg-dark-800 rounded-lg  │
└──────────────────────┴──────────────────────────┘
│ 月度收益热力图 (现有)                            │
└─────────────────────────────────────────────────┘
```

#### 直方图配置
```javascript
series: [{
  type: 'bar',
  itemStyle: {
    color: (params) => params.value >= 0 ? '#22c55e' : '#ef4444'
  }
}]
markLine: {
  data: [{ type: 'average', name: '均值', lineStyle: { color: '#3b82f6' } }]
}
```

#### 统计表规范
```
行：偏度 (Skewness) / 峰度 (Kurtosis) / 最大单次盈利 / 最大单次亏损

偏度解读 badge:
  > 0.5  → 右偏（正向） green
  < -0.5 → 左偏（负向） red
  else   → 对称         gray

峰度解读 badge:
  > 3    → 厚尾（高风险） yellow
  else   → 正态          gray
```

---

### Tab 4: 标的分析

> 保留现有 K 线图 + 月度热力图，无变化。

---

### Tab 5: 逐笔交易深析（NEW）

#### 布局
```
┌─────────────────────────────────────────────────┐
│ MAE/MFE 散点图（ECharts scatter）    高度: 320px │
│  X轴: MAE(最大不利偏移) Y轴: MFE(最大有利偏移)  │
│  点颜色: 盈利=绿 亏损=红                        │
└─────────────────────────────────────────────────┤
│ 逐笔交易表格（可排序）                          │
│  列：# | 入场日 | 出场日 | 入价 | 出价 | 收益率 │
│       | 持仓天 | MAE  | MFE  | 结果badge       │
└─────────────────────────────────────────────────┘
```

#### MAE/MFE 散点图配置
```javascript
series: [{
  type: 'scatter',
  symbolSize: 8,
  itemStyle: {
    color: (params) => params.data[2] > 0 ? '#22c55e' : '#ef4444',
    opacity: 0.7
  }
}]
tooltip: { formatter: '入场: {entry_date}<br>MAE: {x}%<br>MFE: {y}%<br>收益: {ret}%' }
// 参考线: x=0(MAE零线), y=0(MFE零线), 对角线 y=x
markLine: { data: [{ xAxis: 0, lineStyle: { color: '#444' } }, { yAxis: 0, lineStyle: { color: '#444' } }] }
```

#### 交易表格规范
```
容器: bg-dark-700 rounded-xl border border-dark-600 overflow-hidden

表头: bg-dark-800 text-xs text-gray-500 uppercase tracking-wide
      可排序列: cursor-pointer hover:text-white
      排序图标: ▲▼ 内联，激活列 text-accent-blue

表体: text-sm
  斑马纹: even行 bg-dark-800/30
  hover: bg-dark-600/20

结果 badge:
  盈利: bg-green-500/20 text-green-400 text-xs px-2 py-0.5 rounded-full 盈利
  亏损: bg-red-500/20   text-red-400   text-xs px-2 py-0.5 rounded-full 亏损
```

---

### Tab 6: 滚动指标（NEW）

#### 布局
```
┌─────────────────────────────────────────────────┐
│ 滚动 Sharpe/Sortino/波动率（ECharts 多线）       │
│ 高度: 280px                                     │
│ 图例: Sharpe(蓝) / Sortino(紫) / 波动率(黄)    │
└─────────────────────────────────────────────────┤
│ 控制项: 窗口选择 [3M] [6M] [12M]   右对齐      │
└─────────────────────────────────────────────────┘
```

#### 多线图配置
```javascript
legend: { textStyle: { color: '#9ca3af' } }
series: [
  { name: '滚动Sharpe',   type: 'line', color: '#3b82f6', lineWidth: 2, smooth: true },
  { name: '滚动Sortino',  type: 'line', color: '#8b5cf6', lineWidth: 2, smooth: true },
  { name: '滚动波动率',   type: 'line', color: '#eab308', lineWidth: 1.5, smooth: true,
    yAxisIndex: 1  // 双Y轴：右侧为波动率百分比
  }
]
yAxis: [
  { name: '比率', position: 'left',  axisLabel: { formatter: '{value}' } },
  { name: '波动率%', position: 'right', axisLabel: { formatter: '{value}%' } }
]
// 零参考线
markLine: { data: [{ yAxis: 0, lineStyle: { color: '#4b5563', type: 'dashed' } }] }
```

#### 窗口切换按钮
```
容器: flex gap-1 justify-end mb-2

按钮样式（激活）: px-3 py-1 rounded-full text-xs bg-accent-blue text-white
按钮样式（非激活）: px-3 py-1 rounded-full text-xs bg-dark-600 text-gray-400 hover:text-white
```

---

### Tab 7: 高阶统计（Phase 2）

#### 布局（2列网格）
```
┌────────────────┬────────────────────────────────┐
│ VaR/CVaR 指标  │  Monte Carlo 置信锥            │
│ 风险数值卡片   │  (ECharts line, 1000路径)       │
│                │  高度: 280px                   │
├────────────────┼────────────────────────────────┤
│ Omega/PSR/Kelly│  交易时机热力图                 │
│ 高阶统计卡片   │  (ECharts heatmap, 星期×时间)  │
└────────────────┴────────────────────────────────┘
```

#### Monte Carlo 图配置
```javascript
// 1000条路径 → 仅渲染5%/25%/50%/75%/95% 分位线 + 置信带
series: [
  { name: '中位数', type: 'line', color: '#3b82f6', lineWidth: 2 },
  { name: '25%-75%置信', type: 'line', color: 'rgba(59,130,246,0.15)',
    areaStyle: { origin: 'auto' }  // 渐变填充
  },
  { name: '5%-95%置信', type: 'line', color: 'rgba(59,130,246,0.05)',
    areaStyle: { origin: 'auto' }
  }
]
```

#### Phase 2 未实现状态设计
```
Tab 按钮右上角: badge "Phase 2" (bg-purple-500/20 text-purple-400 text-[9px])

内容区加锁遮罩（开发前占位）:
  position: relative
  内容: 半透明 opacity-30
  遮罩: absolute inset-0 flex items-center justify-center
        text: "🔒 Phase 2 功能 — 即将上线"
        text-gray-500 text-sm
```

---

### Tab 8: 平行时空回测（NEW）

> 独立功能，见 Feature 4。

---

## Feature 4: 平行时空回测

### 页面布局（Tab 8 内容区）

```
┌─────────────────────────────────────────────────┐
│ 参数配置行                                      │
│  持仓周期: [30天] [60天] [90天] [180天] [1年]  │
│  步长: [5天] [10天] [20天]   [开始扫描] 按钮   │
└─────────────────────────────────────────────────┤
│ [骨架屏占位 → 加载完成后替换]                  │
│                                                 │
│ 摘要统计（4卡片横排）                           │
│  胜率 | 平均收益 | 最大单次回撤 | 入场次数       │
│                                                 │
│ 散点图（主图）            高度: 380px           │
│  X: 入场日期  Y: 总收益率                      │
│  绿点=盈利  红点=亏损  点大小∝|收益率|         │
│                                                 │
│ 收益分布直方图            高度: 180px           │
└─────────────────────────────────────────────────┤
│ [侧边详情面板] — 点击散点后从右侧滑入          │
│  宽度: 360px, 固定右侧                          │
│  含: 该入场点权益曲线 + 关键指标               │
└─────────────────────────────────────────────────┘
```

### 散点图 ECharts 配置

```javascript
series: [{
  type: 'scatter',
  symbolSize: (val) => Math.max(4, Math.min(20, Math.abs(val[1]) * 2)),  // 大小∝|收益率|
  itemStyle: {
    color: (params) => params.value[1] >= 0
      ? 'rgba(34, 197, 94, 0.7)'    // 正收益 green
      : 'rgba(239, 68, 68, 0.7)',   // 负收益 red
    borderWidth: 0
  },
  emphasis: {
    itemStyle: { borderWidth: 2, borderColor: '#ffffff' }  // hover 白色边框
  }
}]
xAxis: { type: 'time', axisLabel: { color: '#9ca3af', fontSize: 11 } }
yAxis: { axisLabel: { formatter: '{value}%', color: '#9ca3af' } }
tooltip: {
  formatter: (params) =>
    `入场日: ${params.value[0]}<br>` +
    `总收益: <b style="color:${params.value[1]>=0?'#22c55e':'#ef4444'}">${params.value[1].toFixed(2)}%</b><br>` +
    `最大回撤: ${params.value[2].toFixed(2)}%<br>` +
    `Sharpe: ${params.value[3].toFixed(2)}`
}
// 点击事件 → HTMX POST /backtest/parallel/detail
```

### 侧边详情面板规范

```
容器:
  position: fixed; right: 0; top: 0; height: 100vh; width: 360px;
  background: rgba(17, 24, 39, 0.95);   // color-bg-800 + alpha
  backdrop-filter: blur(16px);
  border-left: 1px solid #232b3e;
  transform: translateX(100%);           // 初始隐藏
  transition: transform 0.3s cubic-bezier(0.16, 1, 0.3, 1);

打开态: transform: translateX(0);

头部:
  flex justify-between items-center p-4 border-b border-dark-600
  标题: text-sm font-semibold 入场日期
  关闭按钮: × text-gray-500 hover:text-white

内容区: p-4 overflow-y-auto
  权益曲线: LightweightCharts 高度 200px (同Tab 2配置)
  指标格: 2×3 grid, bg-dark-800 rounded-lg p-3 text-center text-sm
```

### 摘要卡片规范

```
4卡片横排: grid grid-cols-4 gap-3 mb-4

每卡片:
  bg-dark-700 rounded-xl p-4 border border-dark-600 qp-card-enter
  标签: text-xs text-gray-500 mb-1
  数值: text-2xl font-bold qp-number-up
  胜率: color-accent-green if >50% else color-accent-red
  平均收益: color by sign
```

---

## Feature 5: 多策略对比仪表板

### 在 qp_backtest.html 中的位置
Tab 3 内容区（"策略对比"Tab）

### 布局

```
┌─────────────────────────────────────────────────┐
│ 策略多选面板（左侧20%）                         │
│  ┌─────────────────────┐                        │
│  │ ☑ MA Cross          │ 每个策略一行            │
│  │ ☑ Breakout          │ 颜色圆点 + 名称 + 勾选  │
│  │ ☐ RSI Mean Rev      │                        │
│  └─────────────────────┘                        │
│  [对比运行] 按钮 (accent-blue, 全宽)            │
├─────────────────────────────────────────────────┤
│ 叠加权益曲线（LightweightCharts / ECharts）     │
│ 高度: 300px   多色折线（每策略一色）            │
├─────────────────────────────────────────────────┤
│ 策略卡片网格（grid cols=策略数，最多4列）        │
│  每卡片:                                        │
│  ┌───────────────────────────────────────────┐  │
│  │ [色条左侧4px] 策略名          迷你曲线 →  │  │
│  │  年化: +18.4%    回撤: -12.1%             │  │
│  │  Sharpe: 1.84    胜率: 62%                │  │
│  └───────────────────────────────────────────┘  │
├─────────────────────────────────────────────────┤
│ 对比表格（全量指标横向对比）                    │
└─────────────────────────────────────────────────┘
```

### 叠加曲线 ECharts 配置

```javascript
// 颜色池（按顺序分配）
const STRATEGY_COLORS = ['#3b82f6', '#22c55e', '#eab308', '#8b5cf6', '#ef4444', '#06b6d4'];

series: strategies.map((s, i) => ({
  name: s.name,
  type: 'line',
  data: s.equityCurve,
  lineStyle: { color: STRATEGY_COLORS[i], width: 2 },
  itemStyle: { color: STRATEGY_COLORS[i] },
  smooth: false
}))
legend: {
  data: strategies.map(s => s.name),
  textStyle: { color: '#9ca3af' },
  top: 0
}
```

### 策略卡片规范

```
容器: grid gap-3, cols按策略数自动
  1策略: grid-cols-1
  2策略: grid-cols-2
  3策略: grid-cols-3
  4+策略: grid-cols-4 (超出横向滚动)

卡片:
  bg-dark-700 rounded-xl p-4 border-l-4 qp-card-enter
  border-left-color: STRATEGY_COLORS[i]  // 策略代表色
  display: flex; justify-content: space-between; align-items: flex-start

左侧:
  策略名: text-sm font-semibold text-white mb-2
  指标: 2×2 grid
    年化收益 (color by sign)
    最大回撤 (text-accent-red if > 20%)
    Sharpe (text-white)
    胜率 (text-accent-green if > 50%)

右侧: 迷你权益曲线 (sparkline)
  宽度: 80px; 高度: 48px
  ECharts mini: 无坐标轴, 无tooltip, lineWidth 1.5
  颜色: STRATEGY_COLORS[i]
```

### 对比表格规范

```
表格样式: w-full text-sm border-separate border-spacing-0

表头行: bg-dark-800 sticky top-0 z-10
  第一列: 指标名称 (text-gray-500 text-xs)
  其余列: 策略名 + 颜色圆点 (10px圆，STRATEGY_COLORS[i])

数据行: 斑马纹
  最优值高亮: bg-accent-green/10 text-accent-green font-semibold
  最差值高亮: bg-accent-red/10   text-red-400

指标行:
  年化收益率 / 总收益率 / 最大回撤 / Sharpe / Sortino /
  胜率 / 总交易数 / 盈亏比 / Calmar / SQN
```

---

## Feature 6: 回测任务中心

### 路由: `GET /backtest/tasks`
### 文件: `app/templates/qp_backtest_tasks.html`

### 布局

```
┌─────────────────────────────────────────────────┐
│ 页面标题: "回测任务中心"  副标题: 历史任务管理  │
│                           右: [新建回测] 按钮   │
├─────────────────────────────────────────────────┤
│ 过滤栏:                                         │
│  类型: [全部][单次][平行][对比]  状态: [全部][完成][运行中][失败]  │
├─────────────────────────────────────────────────┤
│ 任务列表（每行一个任务）                        │
│  ┌──────────────────────────────────────────┐   │
│  │ 状态dot │ 任务名 + 标的    │ 类型badge │  │   │
│  │         │ 时间/耗时        │ 关键指标  │  │   │
│  │         │ 进度条(运行中时) │           │  │   │
│  └──────────────────────────────────────────┘   │
└─────────────────────────────────────────────────┘
```

### 任务行规范

```
容器: bg-dark-700 rounded-xl border border-dark-600 p-4 mb-2
      hover: border-dark-500 cursor-pointer
      transition: 0.15s
      点击展开详情（accordion 或跳转详情页）

布局: flex items-center gap-4

状态指示器 (16×16px 圆):
  完成: bg-accent-green (实心圆)
  运行中: bg-accent-yellow animate-pulse
  失败: bg-accent-red
  圆心白点: 4×4px

任务名: text-sm font-semibold text-white
标的 badge: text-xs bg-dark-600 text-gray-400 px-2 py-0.5 rounded ml-2

类型 badge:
  单次: bg-blue-500/20 text-blue-400
  平行: bg-purple-500/20 text-purple-400
  对比: bg-yellow-500/20 text-yellow-400
  text-xs px-2 py-0.5 rounded-full

时间: text-xs text-gray-500 (格式: "2026-04-04 14:32" + "耗时 3.2s")

指标组（右侧）: flex gap-4
  年化收益: text-sm font-bold color-by-sign
  Sharpe: text-sm text-white
  胜率: text-sm color-by-sign

进度条（运行中时）:
  高度: 3px; border-radius: full; background: dark-600
  进度: bg-accent-blue; width: {progress}%; transition: width 0.5s
  显示在底部，absolute或flex-col
```

### 空状态设计

```
flex flex-col items-center justify-center py-20
图标: 📋 (48px)
标题: text-lg text-gray-400 "还没有回测任务"
副文字: text-sm text-gray-600 "点击「回测实验室」运行第一个回测"
按钮: bg-accent-blue text-white px-6 py-2 rounded-lg → /backtest
```

---

## Feature 7: 智能组合推荐

### 插入位置
`scan_results.html` 顶部（扫描结果列表之前）

### 布局

```
┌─────────────────────────────────────────────────┐
│ 🧠 智能组合推荐   副: "基于AI评分的最优组合"   │
├───────────────┬──────────────┬──────────────────┤
│  🛡️ 稳健组合   │  ⚔️ 进攻组合  │  ⚖️ 均衡组合     │
│               │              │                  │
│  标的数: 3    │  标的数: 4   │  标的数: 3       │
│  ┌──┐ ┌──┐  │  ┌──┐ ┌──┐  │  ┌──┐ ┌──┐      │
│  │  │ │  │  │  │  │ │  │  │  │  │ │  │      │
│  └──┘ └──┘  │  └──┘ └──┘  │  └──┘ └──┘      │
│  总资金: $8k │  总资金: $12k│  总资金: $10k    │
│  预期收益:   │  预期收益:   │  预期收益:       │
│  12-18%      │  20-35%      │  15-25%          │
│              │              │                  │
│  [加入观察]  │  [加入观察]  │  [加入观察]      │
└───────────────┴──────────────┴──────────────────┘
```

### 组合卡片规范

```
容器: bg-dark-700 rounded-xl border border-dark-600 p-5 qp-card
      flex flex-col gap-3

标题行: flex items-center gap-2
  图标: emoji (20px)
  组合名: text-base font-semibold text-white
  标的数 badge: text-xs bg-dark-500 text-gray-400 px-2 py-0.5 rounded-full

标的 mini 卡片列表: flex flex-wrap gap-2
  每个标的 mini 卡片:
    bg-dark-800 rounded-lg px-3 py-2
    宽度: calc(50% - 4px) 或 auto
    Ticker: text-sm font-bold text-white
    AI评分条: 高度 3px; 颜色渐变 red→yellow→green; 0-100%
    评分数字: text-xs text-gray-400 "AI 82"

底部统计: flex justify-between text-sm
  左: "总资金: $X,XXX"  text-gray-400
  右: "预期收益: XX-XX%"  text-accent-green

加入观察 按钮:
  w-full bg-dark-600 text-gray-300 py-2 rounded-lg text-sm
  hover: bg-dark-500 text-white
  hx-post="/watchlist/add-combo" hx-vals='{"combo_type": "..."}'

稳健 卡片: 边框颜色 border-green-500/30  hover: border-green-500/50
进攻 卡片: 边框颜色 border-red-500/30    hover: border-red-500/50
均衡 卡片: 边框颜色 border-blue-500/30   hover: border-blue-500/50
```

### 加载态骨架屏
```
3个等宽骨架卡片，高度 220px
内含: 标题骨架(100%宽×16px) + 2行迷你卡骨架 + 底部骨架
使用 .qp-skeleton class
```

---

## Feature 8: 持仓监控增强

### 布局总览（全页重构）

```
my_positions.html
┌─────────────────────────────────────────────────┐
│ HERO BNV 区域                                   │
│  $XX,XXX.XX  [countUp from 0]                  │
│  账面净值  +$1,234  (+2.3%)  今日变动          │
│  刷新时间: "实时 · IBKR" or "15分钟前"         │
├─────────────────────────────────────────────────┤
│ 横向滚动持仓条                                  │
│  ← [AAPL +$320] [TSLA -$80] [SPY +$150] ... → │
├─────────────────────────────────────────────────┤
│ KPI 网格（5项，同现有但样式升级）               │
├─────────────────────────────────────────────────┤
│ 期权/正股 Tab 切换                              │
│  [期权 (3)] [正股 (5)]                         │
├─────────────────────────────────────────────────┤
│ 持仓表格（按Tab过滤）                          │
└─────────────────────────────────────────────────┘
```

### Hero BNV 区域规范

```
容器: bg-dark-700 rounded-xl border border-dark-600 p-6 mb-4 qp-card

布局: flex items-end justify-between

左侧:
  标签: text-sm text-gray-500 mb-1 "账面净值 (BNV)"
  数值: text-5xl font-bold text-white qp-number-up data-format="currency"
        countUp duration: 1200ms
  变动行: flex items-center gap-2 mt-1
    日变动金额: text-lg font-semibold color-by-sign "+$1,234"
    日变动百分比: text-sm color-by-sign "(+2.3%)"
    变动方向箭头: ↑ or ↓ (12px)

右侧:
  刷新状态 badge: flex items-center gap-1.5
    实时模式: 绿色圆点 (8px, animate-pulse) + "实时 · IBKR" text-xs text-gray-500
    延迟模式: 灰色圆点 + "15分钟前" text-xs text-gray-600
  [刷新] 按钮: text-gray-600 hover:text-white text-xs flex items-center gap-1
               hx-get="/positions/refresh" hx-target="#hero-bnv"
```

### 横向滚动持仓条规范

```
外容器: overflow-x-auto scrollbar-none mb-4
         -webkit-overflow-scrolling: touch

内容: flex gap-2 pb-1 (不折行)

单个持仓 mini 卡片:
  flex-shrink: 0
  min-width: 120px
  bg-dark-700 rounded-xl border border-dark-600 px-3 py-2
  hover: border-dark-500 transition
  cursor: pointer (点击跳转诊断页)

  Ticker: text-sm font-bold text-white
  P&L: text-xs color-by-sign "+$320" 或 "-$80"
  mini 风险条: 高度 2px mt-1 (现有风险条缩小版)
```

### 期权/正股 Tab 切换规范

```
容器: flex gap-2 mb-3

Tab 按钮（激活）:
  bg-dark-500 text-white px-4 py-1.5 rounded-full text-sm

Tab 按钮（非激活）:
  bg-dark-700 text-gray-400 px-4 py-1.5 rounded-full text-sm border border-dark-600
  hover: text-white

Badge（持仓数量）:
  ml-1.5 bg-dark-600 text-xs px-1.5 py-0.5 rounded-full text-gray-400

交互:
  纯 JS 切换 — 不触发HTMX请求
  对所有持仓行添加 data-type="option" 或 data-type="stock"
  Tab 切换时: rows.forEach(r => r.hidden = r.dataset.type !== activeTab)
  动画: 显示行 fadeInUp 0.3s
```

### 增强持仓卡片规范（表格行）

```
现有列: # | 标的 | 数量 | 入场价 | 当前价 | 未实现P&L | 风险%

新增列（期权）:
  Delta: text-xs font-mono 0.35 (text-accent-blue)
  Theta: text-xs font-mono -0.02 (text-accent-red if negative)
  IV: text-xs font-mono 45%

新增列（正股）:
  支撑位: text-xs text-accent-green "$185.20 (SMA200)"

Delta 颜色规则:
  Long call/delta > 0.5  → text-accent-green
  Short call/delta < -0.5 → text-accent-red
  Near zero              → text-gray-400

支撑位格式:
  text-xs text-accent-green
  "$185.20" (SMA200) or "$182.50" (Swing Low)
```

---

## 骨架屏设计规范（全局）

### 替换规则

| 当前 spinner 位置 | 骨架屏尺寸 |
|-------------------|-----------|
| 回测结果加载 | 3行指标卡骨架 (高度 80px × 7列) + 图表占位 (高度 300px) |
| 扫描结果加载 | 组合推荐骨架 (3块 220px) + 8行结果骨架 (48px/行) |
| 持仓页加载 | Hero骨架 (100px) + 横条骨架 (64px) + 表格行骨架 (48px × 5) |
| 策略对比加载 | 图表骨架 (300px) + 3个卡片骨架 (160px) |
| 平行回测加载 | 散点图骨架 (380px) + 4个摘要卡骨架 |

### 骨架屏 HTML 模式

```html
<!-- 指标卡骨架 (单个) -->
<div class="qp-skeleton h-16 rounded-lg"></div>

<!-- 图表骨架 -->
<div class="qp-skeleton rounded-xl" style="height: 300px;"></div>

<!-- 表格行骨架 -->
<div class="flex gap-3 p-3">
  <div class="qp-skeleton h-4 w-16 rounded"></div>
  <div class="qp-skeleton h-4 flex-1 rounded"></div>
  <div class="qp-skeleton h-4 w-20 rounded"></div>
</div>
```

---

## 响应式断点规范

> 当前 MVP 以桌面端为主，以下为最低保证：

| 断点 | 主要变化 |
|------|---------|
| `>1280px` (xl) | 默认布局，全部功能正常展示 |
| `1024-1280px` (lg) | 策略对比卡片 max 3列，KPI 2行 |
| `768-1024px` (md) | 侧边栏折叠（汉堡菜单），内容全宽 |
| `<768px` (sm) | 持仓横条 mini 卡片宽度 100px，Hero 字体缩到 36px |

---

## 边界情况与空状态规范

| 场景 | 处理方式 |
|------|---------|
| 平行时空扫描无入场点 | "该策略在选定时间段内无有效信号" + 灰色散点区 |
| 策略对比只选1个策略 | Toast 提示 "请至少选择2个策略进行对比" |
| 持仓为空 | 现有空状态卡 + "从观察列表添加" CTA |
| IBKR 断连 | Hero BNV 显示最后同步值 + 黄色警告 badge "已断连 · 最后同步: X分钟前" |
| 组合推荐扫描结果<3个 | 只显示有数据的组合卡，隐藏空的 |
| 高阶统计 Phase 2 未实现 | 锁定遮罩（见 Tab 7 规范） |
| Tab 首次激活无数据 | 骨架屏 500ms → 无数据空状态 |

---

## 可访问性规范

| 元素 | ARIA/键盘规范 |
|------|--------------|
| Tab 导航 | `role="tablist"` + `role="tab"` + `aria-selected` + 键盘左右切换 |
| 侧边栏 | `role="navigation"` + `aria-current="page"` 激活项 |
| 图表容器 | `role="img"` + `aria-label="图表描述"` |
| countUp 数字 | `aria-live="polite"` (动画结束后触发) |
| 骨架屏 | `aria-busy="true"` (加载时) + `aria-busy="false"` (完成后) |
| 散点图点击 | 触发 `focus` 到详情面板，面板有 `role="dialog"` |

---

## 实施优先级

| 优先级 | 功能 | 预估改动规模 |
|--------|------|-------------|
| P0 | qp-animations.css + qp-core.js 创建 | 2个新文件，约200行 |
| P0 | base.html 引入静态文件 | 2行修改 |
| P0 | backtest_inline.html Tab 1 指标升级 | 约50行 |
| P1 | Tab 5 逐笔交易 + MAE/MFE散点 | 新增约120行 |
| P1 | Tab 6 滚动指标 | 新增约80行 |
| P1 | Tab 8 + parallel_backtest.py + 路由 | 最大功能，约400行 |
| P1 | 持仓页 Hero BNV + 横条 + Tab | 修改约150行 |
| P2 | 导航栏重构 | 约80行 |
| P2 | 多策略对比 | 新建约250行 |
| P2 | 任务中心页 | 新建约150行 |
| P2 | 智能组合推荐 | 新建约200行 |
| P3 | Tab 7 高阶统计 (Phase 2) | 约350行 |
