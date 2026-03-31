"""
Goal-Driven Trading OS — Data Models
SQLAlchemy ORM models for Phase 1
"""
from datetime import datetime
from sqlalchemy import create_engine, Column, Integer, Float, String, DateTime, Text, Boolean
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


def init_db():
    """创建所有表 (Phase 1: create_all, Phase 2+: Alembic)"""
    Base.metadata.create_all(engine)


def get_db():
    """FastAPI dependency: 获取数据库 session"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
