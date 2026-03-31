"""
RSI Momentum Strategy — RSI 动量策略
RSI 超卖区域买入，超买区域卖出
"""
import pandas as pd
from strategies.base import StrategyBase, Signal, register_strategy


@register_strategy
class RSIMomentum(StrategyBase):
    name = "rsi_momentum"
    description = "RSI动量策略：RSI跌入超卖区买入，升入超买区卖出"
    default_params = {
        "rsi_period": 14,
        "oversold": 30,
        "overbought": 70,
        "stop_loss_atr_mult": 1.5,
    }

    def generate_signals(self, df: pd.DataFrame) -> list[Signal]:
        signals = []
        oversold = self.params["oversold"]
        overbought = self.params["overbought"]
        atr_mult = self.params["stop_loss_atr_mult"]

        rsi = df.get("rsi_14")
        if rsi is None:
            from ta.momentum import RSIIndicator
            rsi = RSIIndicator(df["close"], window=self.params["rsi_period"]).rsi()

        atr = df.get("atr_14", pd.Series([0] * len(df), index=df.index))
        position_open = False

        for i in range(1, len(df)):
            if pd.isna(rsi.iloc[i]) or pd.isna(rsi.iloc[i - 1]):
                continue

            price = df["close"].iloc[i]
            atr_val = atr.iloc[i] if not pd.isna(atr.iloc[i]) else price * 0.02

            if not position_open and rsi.iloc[i - 1] <= oversold and rsi.iloc[i] > oversold:
                signals.append(Signal(
                    timestamp=df.index[i],
                    symbol="",
                    direction="long",
                    entry_price=price,
                    stop_loss=price - atr_val * atr_mult,
                    strategy_name=self.name,
                ))
                position_open = True

            elif position_open and rsi.iloc[i] >= overbought:
                signals.append(Signal(
                    timestamp=df.index[i],
                    symbol="",
                    direction="close",
                    entry_price=price,
                    strategy_name=self.name,
                ))
                position_open = False

        return signals
