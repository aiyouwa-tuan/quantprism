"""
Bollinger Bands Mean Reversion — 布林带均值回归策略
价格触碰下轨买入，回到中轨或上轨卖出
"""
import pandas as pd
from strategies.base import StrategyBase, Signal, register_strategy


@register_strategy
class BollingerReversion(StrategyBase):
    name = "bollinger_reversion"
    description = "布林带均值回归：触碰下轨买入，回到中轨卖出"
    default_params = {
        "bb_period": 20,
        "bb_std": 2.0,
        "stop_loss_atr_mult": 1.5,
        "exit_at": "mid",  # "mid" or "upper"
    }

    def generate_signals(self, df: pd.DataFrame) -> list[Signal]:
        signals = []
        atr_mult = self.params["stop_loss_atr_mult"]
        exit_at = self.params["exit_at"]

        bb_lower = df.get("bb_lower")
        bb_mid = df.get("bb_mid")
        bb_upper = df.get("bb_upper")

        if bb_lower is None:
            from ta.volatility import BollingerBands
            bb = BollingerBands(df["close"], window=self.params["bb_period"], window_dev=self.params["bb_std"])
            bb_lower = bb.bollinger_lband()
            bb_mid = bb.bollinger_mavg()
            bb_upper = bb.bollinger_hband()

        atr = df.get("atr_14", pd.Series([0] * len(df), index=df.index))
        position_open = False

        for i in range(1, len(df)):
            if pd.isna(bb_lower.iloc[i]):
                continue

            price = df["close"].iloc[i]
            atr_val = atr.iloc[i] if not pd.isna(atr.iloc[i]) else price * 0.02

            if not position_open and price <= bb_lower.iloc[i]:
                signals.append(Signal(
                    timestamp=df.index[i],
                    symbol="",
                    direction="long",
                    entry_price=price,
                    stop_loss=price - atr_val * atr_mult,
                    strategy_name=self.name,
                ))
                position_open = True

            elif position_open:
                exit_level = bb_mid.iloc[i] if exit_at == "mid" else bb_upper.iloc[i]
                if not pd.isna(exit_level) and price >= exit_level:
                    signals.append(Signal(
                        timestamp=df.index[i],
                        symbol="",
                        direction="close",
                        entry_price=price,
                        strategy_name=self.name,
                    ))
                    position_open = False

        return signals
