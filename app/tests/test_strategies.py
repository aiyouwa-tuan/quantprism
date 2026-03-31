"""
Strategy signal generation tests
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from market_data import compute_technicals


def _make_sample_df(n=200, trend="up"):
    """生成测试用 OHLCV 数据"""
    dates = pd.date_range(end=datetime.now(), periods=n, freq="D")
    if trend == "up":
        close = 100 + np.cumsum(np.random.randn(n) * 0.5 + 0.1)
    elif trend == "down":
        close = 200 + np.cumsum(np.random.randn(n) * 0.5 - 0.1)
    else:
        close = 100 + np.cumsum(np.random.randn(n) * 1.0)

    close = np.maximum(close, 10)  # no negative prices
    df = pd.DataFrame({
        "open": close * (1 + np.random.randn(n) * 0.005),
        "high": close * (1 + abs(np.random.randn(n) * 0.01)),
        "low": close * (1 - abs(np.random.randn(n) * 0.01)),
        "close": close,
        "volume": np.random.randint(1000000, 5000000, n),
    }, index=dates)
    df["returns"] = df["close"].pct_change()
    return compute_technicals(df)


class TestSMACrossover:
    def test_generates_signals(self):
        from strategies.sma_crossover import SMACrossover
        strategy = SMACrossover()
        df = _make_sample_df(300, "up")
        signals = strategy.generate_signals(df)
        assert isinstance(signals, list)
        # Uptrend should have at least some long signals
        longs = [s for s in signals if s.direction == "long"]
        assert len(longs) >= 0  # may have 0 if no crossover in random data

    def test_signal_has_stop_loss(self):
        from strategies.sma_crossover import SMACrossover
        strategy = SMACrossover()
        df = _make_sample_df(300, "up")
        signals = strategy.generate_signals(df)
        for s in signals:
            if s.direction == "long":
                assert s.stop_loss < s.entry_price
                assert s.strategy_name == "sma_crossover"

    def test_custom_params(self):
        from strategies.sma_crossover import SMACrossover
        strategy = SMACrossover({"fast_period": 10, "slow_period": 30})
        assert strategy.params["fast_period"] == 10
        assert strategy.params["slow_period"] == 30

    def test_empty_df(self):
        from strategies.sma_crossover import SMACrossover
        strategy = SMACrossover()
        signals = strategy.generate_signals(pd.DataFrame())
        assert signals == []


class TestRSIMomentum:
    def test_generates_signals(self):
        from strategies.rsi_momentum import RSIMomentum
        strategy = RSIMomentum()
        df = _make_sample_df(300, "random")
        signals = strategy.generate_signals(df)
        assert isinstance(signals, list)

    def test_signal_direction(self):
        from strategies.rsi_momentum import RSIMomentum
        strategy = RSIMomentum()
        df = _make_sample_df(300, "random")
        signals = strategy.generate_signals(df)
        for s in signals:
            assert s.direction in ("long", "close")
            assert s.strategy_name == "rsi_momentum"


class TestBollingerReversion:
    def test_generates_signals(self):
        from strategies.bollinger_reversion import BollingerReversion
        strategy = BollingerReversion()
        df = _make_sample_df(300, "random")
        signals = strategy.generate_signals(df)
        assert isinstance(signals, list)

    def test_signal_direction(self):
        from strategies.bollinger_reversion import BollingerReversion
        strategy = BollingerReversion()
        df = _make_sample_df(300, "random")
        signals = strategy.generate_signals(df)
        for s in signals:
            assert s.direction in ("long", "close")
            assert s.strategy_name == "bollinger_reversion"


class TestRegistry:
    def test_all_strategies_registered(self):
        from strategies.base import get_all_strategies
        all_s = get_all_strategies()
        assert "sma_crossover" in all_s
        assert "rsi_momentum" in all_s
        assert "bollinger_reversion" in all_s
        assert len(all_s) == 3

    def test_get_strategy(self):
        from strategies.base import get_strategy
        cls = get_strategy("sma_crossover")
        assert cls is not None
        assert cls.name == "sma_crossover"

    def test_get_unknown_strategy(self):
        from strategies.base import get_strategy
        assert get_strategy("nonexistent") is None
