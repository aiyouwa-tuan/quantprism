"""
策略三：顶部预测 (Top Prediction) | 右侧止盈

战略意图: 识别上涨动能衰竭信号，保护浮盈，执行离场风控。

量化触发条件 (满足以下任意 2 条即拉响警报):
1. 量价异常: 股价接近前高阻力位且呈现缩量状态
2. K线恶化: 出现长上影线 (Shooting Star) 或阴包阳 (Bearish Engulfing)
3. 均线破位: 收盘价有效跌破 5 日均线 (Close < MA5)
4. 动能背离: 股价创新高，但 MACD 红柱缩短（顶背离）

系统行动: 拉响警报，建议 [止盈/减仓]
"""
import pandas as pd
import numpy as np
from strategies.base import StrategyBase, Signal, register_strategy
from ta.trend import SMAIndicator, MACD


@register_strategy
class TopPrediction(StrategyBase):
    name = "top_prediction"
    description = "顶部预测：任意 2 个见顶信号触发 → 止盈/减仓警报"
    default_params = {
        "signals_needed": 2,  # 需要 2 个信号同时触发
        "volume_shrink_pct": 0.7,  # 成交量缩至 20日均量的 70% 以下
        "upper_shadow_ratio": 2.0,  # 上影线长度 >= 实体 2 倍
    }

    def generate_signals(self, df: pd.DataFrame) -> list[Signal]:
        if df.empty or "close" not in df.columns or len(df) < 30:
            return []

        signals = []

        # 计算 MA5
        if "sma_5" not in df.columns:
            df["sma_5"] = SMAIndicator(df["close"], window=5).sma_indicator()

        # 计算 MACD
        macd_ind = MACD(df["close"])
        df["macd_hist"] = macd_ind.macd_diff()

        # 20日均量
        df["vol_ma20"] = df["volume"].rolling(20).mean()

        # 20日最高价 (阻力位)
        df["high_20"] = df["high"].rolling(20).max()

        for i in range(2, len(df)):
            if pd.isna(df["sma_5"].iloc[i]):
                continue

            price = df["close"].iloc[i]
            open_p = df["open"].iloc[i]
            high_p = df["high"].iloc[i]
            low_p = df["low"].iloc[i]
            vol = df["volume"].iloc[i]

            warning_count = 0
            warning_details = []

            # 1. 量价异常: 接近前高 + 缩量
            if not pd.isna(df["high_20"].iloc[i - 1]) and not pd.isna(df["vol_ma20"].iloc[i]):
                near_high = price >= df["high_20"].iloc[i - 1] * 0.98
                low_volume = vol < df["vol_ma20"].iloc[i] * self.params["volume_shrink_pct"]
                if near_high and low_volume:
                    warning_count += 1
                    warning_details.append("量价异常：接近前高但缩量")

            # 2. K线恶化: 长上影线 或 阴包阳
            body = abs(price - open_p)
            upper_shadow = high_p - max(price, open_p)
            if body > 0 and upper_shadow >= body * self.params["upper_shadow_ratio"]:
                warning_count += 1
                warning_details.append("K线恶化：长上影线")

            # 阴包阳
            if i >= 2:
                prev_body_up = df["close"].iloc[i-1] > df["open"].iloc[i-1]
                curr_body_down = price < open_p
                curr_engulfs = open_p > df["close"].iloc[i-1] and price < df["open"].iloc[i-1]
                if prev_body_up and curr_body_down and curr_engulfs:
                    warning_count += 1
                    warning_details.append("K线恶化：阴包阳")

            # 3. 均线破位: 收盘 < MA5
            if price < df["sma_5"].iloc[i] and df["close"].iloc[i-1] >= df["sma_5"].iloc[i-1]:
                warning_count += 1
                warning_details.append(f"均线破位：跌破 MA5 (${df['sma_5'].iloc[i]:.2f})")

            # 4. 动能背离: 价创新高但 MACD 柱缩短
            if not pd.isna(df["macd_hist"].iloc[i]) and not pd.isna(df["macd_hist"].iloc[i-1]):
                price_new_high = price > df["close"].iloc[i-1] and price > df["close"].iloc[i-2]
                macd_weakening = df["macd_hist"].iloc[i] < df["macd_hist"].iloc[i-1] and df["macd_hist"].iloc[i] > 0
                if price_new_high and macd_weakening:
                    warning_count += 1
                    warning_details.append("动能背离：价创新高但 MACD 柱缩短")

            # 满足 2 个以上信号 → 触发警报
            if warning_count >= self.params["signals_needed"]:
                signals.append(Signal(
                    timestamp=df.index[i],
                    symbol="",
                    direction="close",
                    entry_price=price,
                    stop_loss=0,
                    strategy_name=self.name,
                    metadata={
                        "type": "top_warning",
                        "warning_count": warning_count,
                        "warnings": warning_details,
                        "action": "止盈 / 减仓",
                    },
                ))

        return signals
