"""
策略一：待击球 (Waiting to Strike) | 左侧抄底

战略意图: 寻找市场情绪极度恐慌、技术面严重超卖的错杀机会。

量化触发条件 (需同时满足):
- RSI(14) <= 40
- 股价触及或跌破布林带下轨 (Bollinger Lower Band)

系统行动: 触发 [左侧买入/分批建仓] 指令
"""
import pandas as pd
from strategies.base import StrategyBase, Signal, register_strategy


@register_strategy
class WaitingStrike(StrategyBase):
    name = "waiting_strike"
    description = "待击球：RSI <= 40 + 布林带下轨，极度超卖时左侧分批建仓"
    default_params = {
        "rsi_threshold": 40,
        "stop_loss_atr_mult": 2.0,
    }

    def generate_signals(self, df: pd.DataFrame) -> list[Signal]:
        if df.empty or "close" not in df.columns:
            return []

        signals = []
        rsi = df.get("rsi_14")
        bb_lower = df.get("bb_lower")
        atr = df.get("atr_14")

        if rsi is None or bb_lower is None:
            return []

        for i in range(1, len(df)):
            if pd.isna(rsi.iloc[i]) or pd.isna(bb_lower.iloc[i]):
                continue

            price = df["close"].iloc[i]
            atr_val = atr.iloc[i] if atr is not None and not pd.isna(atr.iloc[i]) else price * 0.02

            # 触发: RSI <= 40 且 股价 <= 布林带下轨
            if rsi.iloc[i] <= self.params["rsi_threshold"] and price <= bb_lower.iloc[i]:
                signals.append(Signal(
                    timestamp=df.index[i],
                    symbol="",
                    direction="long",
                    entry_price=price,
                    stop_loss=price - atr_val * self.params["stop_loss_atr_mult"],
                    strategy_name=self.name,
                    metadata={
                        "type": "left_side_entry",
                        "trigger": f"RSI {rsi.iloc[i]:.0f} <= 40 + 价格 ${price:.2f} <= BB下轨 ${bb_lower.iloc[i]:.2f}",
                        "action": "左侧买入 / 分批建仓",
                    },
                ))

        return signals
