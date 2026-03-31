"""
Goal-Driven Trading OS — Position Calculator
核心仓位计算逻辑：从风险目标倒推仓位大小
"""
from dataclasses import dataclass
import math


@dataclass
class PositionResult:
    """仓位计算结果"""
    shares: int                    # 建议股数/合约数
    position_value: float          # 仓位市值
    risk_amount: float             # 该仓位的风险金额
    risk_pct_of_account: float     # 风险占账户百分比
    position_pct_of_account: float # 仓位占账户百分比
    is_capped: bool                # 是否触发上限


@dataclass
class ConstraintResult:
    """目标→约束推导结果"""
    max_positions: int             # 同时持仓上限
    max_position_pct: float        # 单笔最大仓位百分比
    risk_per_trade: float          # 单笔风险比例


def calculate_position_size(
    account_balance: float,
    entry_price: float,
    stop_loss: float,
    risk_per_trade: float = 0.02,
    max_position_pct: float = 1.0,
) -> PositionResult:
    """
    计算建议仓位大小

    公式: 仓位大小 = (账户总资金 × 单笔风险比例) ÷ |入场价 - 止损价|

    Args:
        account_balance: 账户总资金
        entry_price: 入场价格
        stop_loss: 止损价格
        risk_per_trade: 单笔风险比例 (默认 2%)
        max_position_pct: 单笔最大仓位百分比 (从约束推导)
    """
    if account_balance <= 0:
        return PositionResult(
            shares=0, position_value=0, risk_amount=0,
            risk_pct_of_account=0, position_pct_of_account=0, is_capped=False
        )

    if risk_per_trade <= 0:
        return PositionResult(
            shares=0, position_value=0, risk_amount=0,
            risk_pct_of_account=0, position_pct_of_account=0, is_capped=False
        )

    risk_per_share = abs(entry_price - stop_loss)

    if risk_per_share == 0:
        return PositionResult(
            shares=0, position_value=0, risk_amount=0,
            risk_pct_of_account=0, position_pct_of_account=0, is_capped=False
        )

    risk_budget = account_balance * risk_per_trade
    raw_shares = risk_budget / risk_per_share
    shares = math.floor(raw_shares)

    if shares <= 0:
        return PositionResult(
            shares=0, position_value=0, risk_amount=0,
            risk_pct_of_account=0, position_pct_of_account=0, is_capped=False
        )

    # 检查仓位是否超过最大百分比上限
    is_capped = False
    max_value = account_balance * max_position_pct
    position_value = shares * entry_price

    if position_value > max_value and max_position_pct < 1.0:
        shares = math.floor(max_value / entry_price)
        position_value = shares * entry_price
        is_capped = True

    if shares <= 0:
        return PositionResult(
            shares=0, position_value=0, risk_amount=0,
            risk_pct_of_account=0, position_pct_of_account=0, is_capped=is_capped
        )

    risk_amount = shares * risk_per_share
    risk_pct = risk_amount / account_balance
    position_pct = position_value / account_balance

    return PositionResult(
        shares=shares,
        position_value=round(position_value, 2),
        risk_amount=round(risk_amount, 2),
        risk_pct_of_account=round(risk_pct, 4),
        position_pct_of_account=round(position_pct, 4),
        is_capped=is_capped,
    )


def derive_constraints(
    max_drawdown: float,
    risk_per_trade: float,
) -> ConstraintResult:
    """
    从目标推导约束

    公式: 同时持仓上限 = 最大回撤% ÷ 单笔风险%
    假设: 持仓间零相关 (保守估计)

    Args:
        max_drawdown: 最大回撤容忍度 (如 0.10 = 10%)
        risk_per_trade: 单笔风险比例 (如 0.02 = 2%)
    """
    if risk_per_trade <= 0:
        return ConstraintResult(
            max_positions=0,
            max_position_pct=0,
            risk_per_trade=risk_per_trade,
        )

    if max_drawdown <= 0:
        return ConstraintResult(
            max_positions=0,
            max_position_pct=0,
            risk_per_trade=risk_per_trade,
        )

    if max_drawdown < risk_per_trade:
        return ConstraintResult(
            max_positions=1,
            max_position_pct=max_drawdown,
            risk_per_trade=risk_per_trade,
        )

    max_positions = math.floor(max_drawdown / risk_per_trade)
    max_position_pct = max_drawdown / max_positions if max_positions > 0 else 0

    return ConstraintResult(
        max_positions=max_positions,
        max_position_pct=round(max_position_pct, 4),
        risk_per_trade=risk_per_trade,
    )


def check_can_open_position(current_open: int, max_positions: int) -> bool:
    """检查是否可以开新仓"""
    return current_open < max_positions
