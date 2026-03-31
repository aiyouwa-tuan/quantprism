"""
M7 Covered Call 策略
持有正股盈利时，在上涨乏力/阻力位卖出 Call 收权利金

开仓条件:
- 确保正股盈利
- 布林带上轨
- RSI > 70
- 时间选择 30-45 天到期的期权

规则:
- 不卖核心资产，只卖波段资产
- 强劲上涨时不要 covered call
- 仅在上涨乏力时、关键阻力位时 covered call
- 可以来回做波段不停赚权利金
- 或展期、展期+提价
"""
import pandas as pd
from strategies.base import StrategyBase, Signal, register_strategy


@register_strategy
class M7CoveredCall(StrategyBase):
    name = "m7_covered_call"
    description = "M7 Covered Call：正股盈利 + 上涨乏力时卖 Call 收租"
    default_params = {
        "rsi_threshold": 70,
        "dte_target": 30,
        "dte_max": 45,
        "otm_pct": 0.05,  # 5% OTM
    }

    def generate_signals(self, df: pd.DataFrame) -> list[Signal]:
        if df.empty or "close" not in df.columns:
            return []

        signals = []
        rsi = df.get("rsi_14")
        bb_upper = df.get("bb_upper")

        if rsi is None or bb_upper is None:
            return []

        for i in range(1, len(df)):
            if pd.isna(rsi.iloc[i]) or pd.isna(bb_upper.iloc[i]):
                continue

            price = df["close"].iloc[i]

            # 开仓: RSI > 70 且触碰布林带上轨（上涨乏力）
            if rsi.iloc[i] > self.params["rsi_threshold"] and price >= bb_upper.iloc[i] * 0.99:
                strike = round(price * (1 + self.params["otm_pct"]) / 5) * 5
                signals.append(Signal(
                    timestamp=df.index[i],
                    symbol="",
                    direction="short",  # 卖 Call
                    entry_price=price,
                    stop_loss=0,
                    strategy_name=self.name,
                    metadata={
                        "type": "covered_call",
                        "strike": strike,
                        "dte": self.params["dte_target"],
                        "note": "仅在正股盈利时操作，不卖核心资产",
                    },
                ))

        return signals
