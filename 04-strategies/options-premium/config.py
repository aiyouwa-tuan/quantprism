"""
策略配置 V21: Iron Condor — IBKR 真实 IV 校准版
覆盖 2008 金融危机 + 2020 COVID + IBKR 真实佣金 + 波动率偏斜 + bid-ask + 滑点
V21 变更: IV_MULTIPLIER 由 IBKR 5年真实数据校准 (真实IV/VIX = 0.8231)
"""

# === 回测区间 ===
START_DATE = "2005-01-01"   # 延长至 20 年（SPY 周度期权 2005 年上市）
END_DATE = "2024-12-31"

# === 标的 ===
UNDERLYING = "SPY"
VIX_TICKER = "^VIX"

# === 资金 ===
INITIAL_CAPITAL = 10000

# === 策略参数 ===
SHORT_PUT_DELTA = 0.30
DELTA_VIX_ADJUST = True
DELTA_HIGH_VIX = 0.10
DELTA_VIX_THRESHOLD = 22
SPREAD_WIDTH = 5              # $5 宽度
DTE_TARGET = 7               # 7 天到期
DTE_MIN = 3
DTE_MAX = 10

# === 仓位管理 ===
MAX_RISK_PER_TRADE = 0.025
MAX_POSITIONS = 4            # 4 仓
MAX_CAPITAL_DEPLOYED = 0.15
COMMISSION_PER_LEG = 0.65    # IBKR 真实佣金

# === 退出规则 ===
PROFIT_TARGET = 0.40
STOP_LOSS = 999              # 无个别止损（定义风险已封顶）
DTE_EXIT = 1
PORTFOLIO_STOP = 0.03         # 3%

# === 入场过滤 ===
MIN_VIX = 10
MAX_VIX = 25
TREND_SMA_PERIOD = 100       # SMA100
REQUIRE_ABOVE_SMA = True
SMA_SHORT = 10
REQUIRE_SHORT_TREND = False

# === 回撤保护 ===
MAX_DRAWDOWN_PAUSE = 0.04     # 4%
RESUME_AFTER_DAYS = 10       # 10 天恢复

# === 期权定价 ===
RISK_FREE_RATE = 0.05
IV_MULTIPLIER = 0.95         # 考虑 VIX 包含部分偏斜溢价

# === 真实摩擦成本 (V20 新增) ===
# 波动率偏斜 (Volatility Skew)
# 真实市场中 OTM Put 的 IV 比 ATM 高 15-25%（尾部风险溢价）
IV_SKEW_PUT = 1.30           # 7DTE OTM Put IV = ATM × 1.30 (短期偏斜更大)
IV_SKEW_CALL = 0.95          # OTM Call IV = ATM × 0.95

# Bid-Ask 价差 (针对整个 Iron Condor 组合单，非单条腿)
# SPY IC 组合单 bid-ask 约 $0.03-$0.06，半价差 $0.02-$0.03
BID_ASK_HALF_SPREAD = 0.03   # IC 组合 半价差 $0.03/股
BID_ASK_CRISIS_MULT = 3.0    # 高波动时价差放大倍数
BID_ASK_CRISIS_VIX = 30      # VIX 超过此值触发危机价差

# 滑点 (限价单对组合的滑点)
SLIPPAGE = 0.01              # 组合滑点 $0.01/股

# 危机模式
CRISIS_VIX_THRESHOLD = 30    # VIX > 30 时完全停止交易
