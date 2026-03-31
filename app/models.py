"""
Goal-Driven Trading OS — Data Models
SQLAlchemy ORM models for all phases
"""
from datetime import datetime
from sqlalchemy import create_engine, Column, Integer, Float, String, DateTime, Text, Boolean, UniqueConstraint, JSON
from sqlalchemy.orm import declarative_base, sessionmaker

DATABASE_URL = "sqlite:///trading_os.db"

engine = create_engine(DATABASE_URL, echo=False)
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()


class UserGoals(Base):
    """用户的收益/风险目标"""
    __tablename__ = "user_goals"

    id = Column(Integer, primary_key=True)
    annual_return_target = Column(Float, nullable=False)  # 年化收益目标 (如 0.15 = 15%)
    max_drawdown = Column(Float, nullable=False)           # 最大回撤容忍度 (如 0.10 = 10%)
    risk_per_trade = Column(Float, default=0.02)           # 单笔风险比例 (默认 2%)
    # 系统推导的约束
    max_positions = Column(Integer)                         # 同时持仓上限
    max_position_pct = Column(Float)                        # 单笔最大仓位百分比
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Position(Base):
    """当前持仓记录"""
    __tablename__ = "positions"

    id = Column(Integer, primary_key=True)
    symbol = Column(String(20), nullable=False)
    market = Column(String(10), default="stock")  # stock / crypto / option
    entry_price = Column(Float, nullable=False)
    stop_loss = Column(Float, nullable=False)
    quantity = Column(Float, nullable=False)       # 股数或合约数
    entry_date = Column(DateTime, default=datetime.utcnow)
    is_open = Column(Boolean, default=True)
    close_price = Column(Float, nullable=True)
    close_date = Column(DateTime, nullable=True)
    # 计算字段 (入场时计算并存储)
    risk_amount = Column(Float)                    # 该仓位的风险金额
    risk_pct_of_account = Column(Float)            # 该仓位风险占总资金百分比
    account_balance_at_entry = Column(Float)       # 入场时账户总资金
    # Phase 1.5: Broker sync
    source = Column(String(20), default="manual")  # manual / broker
    current_price = Column(Float, nullable=True)
    unrealized_pnl = Column(Float, nullable=True)


class TradeJournal(Base):
    """交易决策日志 (Expansion #1)"""
    __tablename__ = "trade_journal"

    id = Column(Integer, primary_key=True)
    position_id = Column(Integer, nullable=True)   # 关联持仓 (可选)
    symbol = Column(String(20), nullable=False)
    action = Column(String(10), nullable=False)     # buy / sell / close
    entry_reason = Column(Text, nullable=True)      # 进场理由
    market_conditions = Column(Text, nullable=True) # 市场条件描述
    emotional_state = Column(String(20), nullable=True)  # confident / rushing / chasing / fearful
    vix_at_entry = Column(Float, nullable=True)     # VIX 值 (手动填写)
    trend_at_entry = Column(String(20), nullable=True)   # uptrend / downtrend / sideways
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class JournalCompliance(Base):
    """日志填写率追踪 (智能提醒用)"""
    __tablename__ = "journal_compliance"

    id = Column(Integer, primary_key=True)
    trades_without_journal = Column(Integer, default=0)  # 连续未填写日志的交易数
    last_reminder_date = Column(DateTime, nullable=True)
    total_trades = Column(Integer, default=0)
    total_journaled = Column(Integer, default=0)


class MarketDataCache(Base):
    """市场数据缓存 (Phase 1.5)"""
    __tablename__ = "market_data_cache"
    __table_args__ = (UniqueConstraint("symbol", "date", name="uq_symbol_date"),)

    id = Column(Integer, primary_key=True)
    symbol = Column(String(20), nullable=False, index=True)
    date = Column(DateTime, nullable=False)
    open = Column(Float)
    high = Column(Float)
    low = Column(Float)
    close = Column(Float)
    volume = Column(Float)
    source = Column(String(20), default="yfinance")


class StrategyConfig(Base):
    """策略配置 (Phase 2)"""
    __tablename__ = "strategy_configs"

    id = Column(Integer, primary_key=True)
    strategy_name = Column(String(50), nullable=False)
    symbol = Column(String(20), default="SPY")
    params_yaml = Column(Text)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class BacktestRun(Base):
    """回测运行记录 (Phase 2)"""
    __tablename__ = "backtest_runs"

    id = Column(Integer, primary_key=True)
    strategy_config_id = Column(Integer, nullable=False)
    run_type = Column(String(20))  # full / walk_forward / stress_test
    period_label = Column(String(50))
    start_date = Column(String(20))
    end_date = Column(String(20))
    total_return = Column(Float)
    annual_return = Column(Float)
    max_drawdown = Column(Float)
    sharpe_ratio = Column(Float)
    sortino_ratio = Column(Float)
    win_rate = Column(Float)
    total_trades = Column(Integer)
    profit_factor = Column(Float)
    equity_curve_json = Column(Text)
    trades_json = Column(Text)
    compatible_with_goals = Column(Boolean)
    created_at = Column(DateTime, default=datetime.utcnow)


class TradeSignal(Base):
    """交易信号 (Phase 2/4)"""
    __tablename__ = "trade_signals"

    id = Column(Integer, primary_key=True)
    strategy_config_id = Column(Integer, nullable=True)
    symbol = Column(String(20), nullable=False)
    direction = Column(String(10))  # long / short / close
    signal_price = Column(Float)
    signal_stop_loss = Column(Float)
    signal_take_profit = Column(Float)
    signal_quantity = Column(Float)
    confidence = Column(Float)
    signal_time = Column(DateTime, default=datetime.utcnow)
    status = Column(String(20), default="pending")  # pending / confirmed / executed / skipped / expired
    execution_price = Column(Float, nullable=True)
    execution_quantity = Column(Float, nullable=True)
    execution_time = Column(DateTime, nullable=True)
    position_id = Column(Integer, nullable=True)
    deviation_reason = Column(Text, nullable=True)


class StrategyLeaderboard(Base):
    """策略排行榜 (Phase 2, Expansion #4)"""
    __tablename__ = "strategy_leaderboard"

    id = Column(Integer, primary_key=True)
    strategy_name = Column(String(50), nullable=False)
    regime = Column(String(20))  # low_vol / normal / mid_vol / high_vol
    sharpe_ratio = Column(Float)
    annual_return = Column(Float)
    max_drawdown = Column(Float)
    win_rate = Column(Float)
    total_trades = Column(Integer)
    updated_at = Column(DateTime, default=datetime.utcnow)


class ExecutionLog(Base):
    """执行记录 (Phase 4)"""
    __tablename__ = "execution_log"

    id = Column(Integer, primary_key=True)
    signal_id = Column(Integer, nullable=True)
    position_id = Column(Integer, nullable=True)
    symbol = Column(String(20), nullable=False)
    side = Column(String(10))
    order_type = Column(String(20))
    requested_qty = Column(Float)
    filled_qty = Column(Float, nullable=True)
    requested_price = Column(Float, nullable=True)
    filled_price = Column(Float, nullable=True)
    broker_order_id = Column(String(50), nullable=True)
    status = Column(String(20), default="submitted")
    submitted_at = Column(DateTime, default=datetime.utcnow)
    filled_at = Column(DateTime, nullable=True)
    error_message = Column(Text, nullable=True)


class AlertConfig(Base):
    """告警配置 (Phase 5)"""
    __tablename__ = "alert_config"

    id = Column(Integer, primary_key=True)
    feishu_webhook_url = Column(Text, nullable=True)
    sms_enabled = Column(Boolean, default=False)
    sms_phone = Column(String(20), nullable=True)
    drawdown_warn_pct = Column(Float, default=0.05)
    drawdown_critical_pct = Column(Float, default=0.08)
    single_position_loss_pct = Column(Float, default=0.03)
    gap_threshold_pct = Column(Float, default=0.005)
    vix_spike_threshold = Column(Float, default=30.0)
    rate_limit_minutes = Column(Integer, default=60)
    is_active = Column(Boolean, default=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class AlertHistory(Base):
    """告警历史 (Phase 5)"""
    __tablename__ = "alert_history"

    id = Column(Integer, primary_key=True)
    alert_type = Column(String(30))
    title = Column(String(200))
    body = Column(Text)
    position_id = Column(Integer, nullable=True)
    channel = Column(String(20))  # feishu / sms / both
    was_rate_limited = Column(Boolean, default=False)
    delivered = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class ApiConfig(Base):
    """API 配置 (统一管理所有外部服务密钥)"""
    __tablename__ = "api_config"

    id = Column(Integer, primary_key=True)
    service_name = Column(String(50), nullable=False, unique=True)  # alpaca / ccxt_binance / feishu / twilio
    display_name = Column(String(100))
    api_key = Column(Text, nullable=True)
    api_secret = Column(Text, nullable=True)
    extra_config = Column(Text, nullable=True)  # JSON for additional fields
    is_active = Column(Boolean, default=False)
    status = Column(String(20), default="未配置")  # 未配置 / 已配置 / 已验证 / 错误
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


def init_db():
    """创建所有表"""
    Base.metadata.create_all(engine)


def get_db():
    """FastAPI dependency: 获取数据库 session"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
