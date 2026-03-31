"""
Backtester tests — portfolio simulation + metrics
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import numpy as np
from datetime import datetime
from backtester import _simulate_portfolio
from strategies.base import Signal


def _make_signals():
    """Create known signals for deterministic testing"""
    return [
        Signal(timestamp=datetime(2024, 1, 10), symbol="TEST", direction="long",
               entry_price=100.0, stop_loss=95.0, strategy_name="test"),
        Signal(timestamp=datetime(2024, 2, 10), symbol="TEST", direction="close",
               entry_price=110.0, strategy_name="test"),
        Signal(timestamp=datetime(2024, 3, 10), symbol="TEST", direction="long",
               entry_price=105.0, stop_loss=100.0, strategy_name="test"),
        Signal(timestamp=datetime(2024, 4, 10), symbol="TEST", direction="close",
               entry_price=95.0, strategy_name="test"),
    ]


def _make_df(n=100):
    dates = pd.date_range(start="2024-01-01", periods=n, freq="D")
    return pd.DataFrame({"close": np.linspace(100, 110, n)}, index=dates)


class TestSimulatePortfolio:
    def test_basic_pnl(self):
        signals = _make_signals()
        df = _make_df()
        metrics = _simulate_portfolio(signals, df, initial_capital=10000, risk_per_trade=0.02)

        # Trade 1: buy 100, sell 110, risk_per_share=5, shares=floor(200/5)=40, pnl=40*10=400
        # Trade 2: buy 105, sell 95, risk_per_share=5, shares=floor(200/5)=40..but capital changed
        assert metrics.total_trades == 2
        assert metrics.final_equity != 10000  # something changed

    def test_win_rate(self):
        signals = _make_signals()
        df = _make_df()
        metrics = _simulate_portfolio(signals, df)
        # First trade wins (+10 per share), second loses (-10 per share)
        assert metrics.win_rate == 0.5

    def test_empty_signals(self):
        df = _make_df()
        metrics = _simulate_portfolio([], df)
        assert metrics.total_trades == 0
        assert metrics.final_equity == 10000

    def test_equity_curve_grows(self):
        # Only winning trades
        signals = [
            Signal(timestamp=datetime(2024, 1, 10), symbol="T", direction="long",
                   entry_price=100, stop_loss=95, strategy_name="t"),
            Signal(timestamp=datetime(2024, 2, 10), symbol="T", direction="close",
                   entry_price=120, strategy_name="t"),
        ]
        df = _make_df()
        metrics = _simulate_portfolio(signals, df)
        assert metrics.final_equity > 10000
        assert metrics.total_return > 0
        assert metrics.max_drawdown <= 0  # drawdown is negative or zero

    def test_sharpe_ratio_calculated(self):
        signals = _make_signals()
        df = _make_df()
        metrics = _simulate_portfolio(signals, df)
        assert isinstance(metrics.sharpe_ratio, float)

    def test_zero_risk_per_share_skipped(self):
        signals = [
            Signal(timestamp=datetime(2024, 1, 10), symbol="T", direction="long",
                   entry_price=100, stop_loss=100, strategy_name="t"),  # stop = entry
        ]
        df = _make_df()
        metrics = _simulate_portfolio(signals, df)
        assert metrics.total_trades == 0

    def test_profit_factor(self):
        signals = _make_signals()
        df = _make_df()
        metrics = _simulate_portfolio(signals, df)
        assert isinstance(metrics.profit_factor, float)
        assert metrics.profit_factor >= 0
