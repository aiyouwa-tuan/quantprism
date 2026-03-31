"""
SMA Crossover Strategy — 双均线交叉
当快速均线从下方穿越慢速均线时买入，从上方穿越时卖出
"""
import pandas as pd
from strategies.base import StrategyBase, Signal, register_strategy


@register_strategy
class SMACrossover(StrategyBase):
    name = "sma_crossover"
    description = "双均线交叉策略：快速SMA上穿慢速SMA时买入，下穿时卖出"
    default_params = {
        "fast_period": 20,
        "slow_period": 50,
        "stop_loss_atr_mult": 2.0,
    }

    def generate_signals(self, df: pd.DataFrame) -> list[Signal]:
        if df.empty or "close" not in df.columns:
            return []
        signals = []
        fast = self.params["fast_period"]
        slow = self.params["slow_period"]
        atr_mult = self.params["stop_loss_atr_mult"]

        if f"sma_{fast}" not in df.columns:
            from ta.trend import SMAIndicator
            df[f"sma_{fast}"] = SMAIndicator(df["close"], window=fast).sma_indicator()
        if f"sma_{slow}" not in df.columns:
            from ta.trend import SMAIndicator
            df[f"sma_{slow}"] = SMAIndicator(df["close"], window=slow).sma_indicator()

        sma_fast = df[f"sma_{fast}"]
        sma_slow = df[f"sma_{slow}"]
        atr = df.get("atr_14", pd.Series([0] * len(df), index=df.index))

        position_open = False

        for i in range(1, len(df)):
            if pd.isna(sma_fast.iloc[i]) or pd.isna(sma_slow.iloc[i]):
                continue

            prev_fast_above = sma_fast.iloc[i - 1] > sma_slow.iloc[i - 1]
            curr_fast_above = sma_fast.iloc[i] > sma_slow.iloc[i]
            price = df["close"].iloc[i]
            atr_val = atr.iloc[i] if not pd.isna(atr.iloc[i]) else price * 0.02

            if not position_open and not prev_fast_above and curr_fast_above:
                signals.append(Signal(
                    timestamp=df.index[i],
                    symbol="",
                    direction="long",
                    entry_price=price,
                    stop_loss=price - atr_val * atr_mult,
                    strategy_name=self.name,
                ))
                position_open = True

            elif position_open and prev_fast_above and not curr_fast_above:
                signals.append(Signal(
                    timestamp=df.index[i],
                    symbol="",
                    direction="close",
                    entry_price=price,
                    strategy_name=self.name,
                ))
                position_open = False

        return signals
