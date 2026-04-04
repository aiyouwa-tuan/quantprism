"""
Covered Call 策略（持股收租）
模拟 Covered Call：持有正股 + RSI 高位时卖 Call 收权利金

由于无法直接交易期权，采用股价模拟：
- SMA50 上方 + RSI 40-65：买入（持有正股阶段）
- RSI > 72 或触碰布林带上轨：平仓（模拟卖出 Call 锁定收益）
- 价格跌破 SMA50：止损平仓
"""
import pandas as pd
from strategies.base import StrategyBase, Signal, register_strategy


@register_strategy
class CoveredCall(StrategyBase):
    name = "covered_call"
    description = "Covered Call 收租策略：SMA 趋势持仓 + RSI 高位卖 Call 锁定收益"
    default_params = {
        "sma_period": 50,
        "rsi_entry_min": 40,
        "rsi_entry_max": 65,
        "rsi_exit": 72,
        "sma_buffer": 0.97,  # 跌破 SMA * 0.97 时止损
    }

    def generate_signals(self, df: pd.DataFrame) -> list[Signal]:
        if df.empty or "close" not in df.columns:
            return []

        signals = []
        sma_col = f"sma_{self.params['sma_period']}"
        rsi_col = "rsi_14"
        bb_upper_col = "bb_upper"

        sma = df.get(sma_col)
        rsi = df.get(rsi_col)
        bb_upper = df.get(bb_upper_col)

        if sma is None or rsi is None:
            return []

        in_position = False

        for i in range(1, len(df)):
            if pd.isna(rsi.iloc[i]) or pd.isna(sma.iloc[i]):
                continue

            price = df["close"].iloc[i]
            sma_val = sma.iloc[i]
            rsi_val = rsi.iloc[i]
            bb_val = bb_upper.iloc[i] if bb_upper is not None and not pd.isna(bb_upper.iloc[i]) else float("inf")

            if not in_position:
                # 入场：价格在 SMA 上方 + RSI 处于合理区间（非超买）
                if (price > sma_val and
                        self.params["rsi_entry_min"] <= rsi_val <= self.params["rsi_entry_max"]):
                    signals.append(Signal(
                        timestamp=df.index[i],
                        symbol="",
                        direction="long",
                        entry_price=price,
                        stop_loss=sma_val * self.params["sma_buffer"],
                        strategy_name=self.name,
                        metadata={"note": "持股阶段入场"},
                    ))
                    in_position = True
            else:
                # 出场：RSI 超买（模拟卖 Call 收权利金）或跌破 SMA 止损
                exit_rsi = rsi_val > self.params["rsi_exit"]
                exit_bb = price >= bb_val * 0.995
                exit_sma = price < sma_val * self.params["sma_buffer"]

                if exit_rsi or exit_bb or exit_sma:
                    reason = "RSI超买卖Call" if (exit_rsi or exit_bb) else "SMA止损"
                    signals.append(Signal(
                        timestamp=df.index[i],
                        symbol="",
                        direction="close",
                        entry_price=price,
                        strategy_name=self.name,
                        metadata={"note": reason},
                    ))
                    in_position = False

        return signals
