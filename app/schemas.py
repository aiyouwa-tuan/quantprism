"""
Goal-Driven Trading OS — Pydantic Schemas
输入验证 + 响应序列化
"""
from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime


class GoalsCreate(BaseModel):
    annual_return_target: float = Field(..., gt=0, le=5.0, description="年化收益目标 (如 0.15 = 15%)")
    max_drawdown: float = Field(..., gt=0, le=1.0, description="最大回撤容忍度 (如 0.10 = 10%)")
    risk_per_trade: float = Field(0.02, gt=0, le=0.1, description="单笔风险比例 (默认 2%)")


class PositionCreate(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=20)
    market: str = Field("stock", pattern="^(stock|crypto|option)$")
    entry_price: float = Field(..., gt=0)
    stop_loss: float = Field(..., gt=0)
    quantity: float = Field(..., gt=0)
    account_balance: float = Field(..., gt=0, description="当前账户总资金")
    entry_reason: Optional[str] = None
    emotional_state: Optional[str] = Field(None, pattern="^(confident|rushing|chasing|fearful|calm|uncertain)?$")
    vix_at_entry: Optional[float] = Field(None, ge=0, le=100)
    trend_at_entry: Optional[str] = Field(None, pattern="^(uptrend|downtrend|sideways)?$")


class CalculateRequest(BaseModel):
    account_balance: float = Field(..., gt=0)
    entry_price: float = Field(..., gt=0)
    stop_loss: float = Field(..., gt=0)
    risk_per_trade: Optional[float] = Field(None, gt=0, le=0.1)


class JournalCreate(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=20)
    action: str = Field(..., pattern="^(buy|sell|close)$")
    entry_reason: Optional[str] = None
    market_conditions: Optional[str] = None
    emotional_state: Optional[str] = Field(None, pattern="^(confident|rushing|chasing|fearful|calm|uncertain)?$")
    vix_at_entry: Optional[float] = Field(None, ge=0, le=100)
    trend_at_entry: Optional[str] = Field(None, pattern="^(uptrend|downtrend|sideways)?$")
    notes: Optional[str] = None
    position_id: Optional[int] = None


class PositionClose(BaseModel):
    close_price: float = Field(..., gt=0)
