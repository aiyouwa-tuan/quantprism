"""
Strategy Base — abstract base class + registry
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
import pandas as pd


@dataclass
class Signal:
    timestamp: datetime
    symbol: str
    direction: str  # "long", "short", "close"
    entry_price: float
    stop_loss: float = 0
    take_profit: float = 0
    confidence: float = 1.0
    strategy_name: str = ""
    metadata: dict = field(default_factory=dict)


@dataclass
class BacktestMetrics:
    total_return: float = 0
    annual_return: float = 0
    max_drawdown: float = 0
    sharpe_ratio: float = 0
    sortino_ratio: float = 0
    win_rate: float = 0
    total_trades: int = 0
    profit_factor: float = 0
    avg_win: float = 0
    avg_loss: float = 0
    final_equity: float = 0
    equity_curve: list = field(default_factory=list)
    trades: list = field(default_factory=list)
    max_consecutive_losses: int = 0
    avg_holding_days: float = 0
    daily_details: list = None
    # Phase 1 enhancements
    calmar_ratio: float = 0
    sqn_score: float = 0
    sqn_grade: str = ""
    best_trade: float = 0
    worst_trade: float = 0
    avg_trade_return: float = 0
    rolling_sharpe: list = field(default_factory=list)
    rolling_sortino: list = field(default_factory=list)
    rolling_volatility: list = field(default_factory=list)
    trade_details: list = field(default_factory=list)
    # Phase 2: Advanced Statistics
    var_95: float = 0
    cvar_95: float = 0
    omega_ratio: float = 0
    psr: float = 0
    kelly_full: float = 0
    kelly_half: float = 0
    monte_carlo: dict = field(default_factory=dict)
    trade_heatmap: list = field(default_factory=list)


STRATEGY_REGISTRY: dict[str, type] = {}


def register_strategy(cls):
    STRATEGY_REGISTRY[cls.name] = cls
    return cls


def get_all_strategies() -> dict:
    return STRATEGY_REGISTRY


def get_strategy(name: str):
    return STRATEGY_REGISTRY.get(name)


class StrategyBase(ABC):
    name: str = "base"
    description: str = ""
    default_params: dict = {}

    def __init__(self, params: dict = None):
        self.params = {**self.default_params}
        if params:
            self.params.update(params)

    @abstractmethod
    def generate_signals(self, df: pd.DataFrame) -> list[Signal]:
        """Generate trading signals from OHLCV data with technical indicators"""
        pass

    @classmethod
    def get_param_schema(cls) -> dict:
        return cls.default_params
