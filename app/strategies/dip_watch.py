"""
策略二：回马枪 (Dip Watch) | 顺势低吸

战略意图: 在趋势确立的背景下，寻找强势标的的健康缩量回调节点。

量化触发条件 (需同时满足):
- RSI(14) 处于 [45, 55] 震荡/中性区间
- 股价回踩关键均线 (MA10 / MA20) 或已确认的支撑位

系统行动: 触发 [倒车接人/顺势加仓] 指令
"""
import pandas as pd
from strategies.base import StrategyBase, Signal, register_strategy
from ta.trend import SMAIndicator


@register_strategy
class DipWatch(StrategyBase):
    name = "dip_watch"
    description = "回马枪：RSI 45-55 中性区 + 回踩 MA10/MA20，顺势低吸"
    default_params = {
        "rsi_low": 45,
        "rsi_high": 55,
        "ma_touch_tolerance": 0.005,  # 允许 0.5% 的误差
        "stop_loss_atr_mult": 1.5,
    }

    def generate_signals(self, df: pd.DataFrame) -> list[Signal]:
        if df.empty or "close" not in df.columns:
            return []

        signals = []
        rsi = df.get("rsi_14")
        sma_20 = df.get("sma_20")
        atr = df.get("atr_14")

        # 计算 MA10
        if "sma_10" not in df.columns and len(df) >= 10:
            df["sma_10"] = SMAIndicator(df["close"], window=10).sma_indicator()
        sma_10 = df.get("sma_10")

        if rsi is None or sma_20 is None:
            return []

        for i in range(1, len(df)):
            if pd.isna(rsi.iloc[i]) or pd.isna(sma_20.iloc[i]):
                continue

            price = df["close"].iloc[i]
            atr_val = atr.iloc[i] if atr is not None and not pd.isna(atr.iloc[i]) else price * 0.02
            tol = self.params["ma_touch_tolerance"]

            # RSI 在中性区 [45, 55]
            rsi_ok = self.params["rsi_low"] <= rsi.iloc[i] <= self.params["rsi_high"]
            if not rsi_ok:
                continue

            # 回踩 MA10 或 MA20
            touch_ma20 = abs(price - sma_20.iloc[i]) / sma_20.iloc[i] <= tol
            touch_ma10 = False
            if sma_10 is not None and not pd.isna(sma_10.iloc[i]):
                touch_ma10 = abs(price - sma_10.iloc[i]) / sma_10.iloc[i] <= tol

            if touch_ma10 or touch_ma20:
                ma_touched = "MA10" if touch_ma10 else "MA20"
                signals.append(Signal(
                    timestamp=df.index[i],
                    symbol="",
                    direction="long",
                    entry_price=price,
                    stop_loss=price - atr_val * self.params["stop_loss_atr_mult"],
                    strategy_name=self.name,
                    metadata={
                        "type": "trend_pullback",
                        "trigger": f"RSI {rsi.iloc[i]:.0f} 中性 + 回踩 {ma_touched}",
                        "action": "倒车接人 / 顺势加仓",
                    },
                ))

        return signals
