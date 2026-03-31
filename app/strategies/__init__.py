from strategies.base import StrategyBase, Signal, BacktestMetrics, STRATEGY_REGISTRY, get_all_strategies, get_strategy

# 原有策略
from strategies.sma_crossover import SMACrossover
from strategies.rsi_momentum import RSIMomentum
from strategies.bollinger_reversion import BollingerReversion

# 用户自定义策略
from strategies.m7_leaps import M7Leaps
from strategies.m7_covered_call import M7CoveredCall
from strategies.tqqq_dip import TQQQDip
from strategies.qqq_leaps import QQQLeaps
from strategies.waiting_strike import WaitingStrike
from strategies.dip_watch import DipWatch
from strategies.top_prediction import TopPrediction
