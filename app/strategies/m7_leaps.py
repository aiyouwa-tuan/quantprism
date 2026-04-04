"""
M7 LEAPS 策略
大科技股（AAPL/MSFT/GOOGL/AMZN/NVDA/META/TSLA）在超卖时买入长期看涨期权

开仓条件:
- VIX > 15（市场不过度自信，建议 15-25）
- 布林带下轨
- RSI <= 40
- 买入 delta 约 0.7 的期权
- 总体仓位 <= 10%-20%

出仓条件:
- 7天内 10-20%，立即落袋
- 4周内 20-40%，止盈
- >= 100%，强烈建议止盈
- 到期前 90 天，无论盈亏必须平仓
"""
import pandas as pd
from strategies.base import StrategyBase, Signal, register_strategy


M7_SYMBOLS = ["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA"]


@register_strategy
class M7Leaps(StrategyBase):
    name = "m7_leaps"
    description = "M7 LEAPS：大科技股超卖时买入 delta 0.7 的长期 Call"
    default_params = {
        "vix_min": 15,
        "vix_max": 25,
        "rsi_threshold": 40,
        "delta_target": 0.7,
        "max_position_pct": 0.20,
        # 止盈规则
        "profit_7d": 0.10,    # 7天内 10% 落袋
        "profit_4w": 0.20,    # 4周内 20% 止盈
        "profit_strong": 1.0, # 100% 强烈止盈
        "force_close_dte": 90, # 到期前 90 天强平（用交易日近似）
        "symbols": M7_SYMBOLS,
    }

    def generate_signals(self, df: pd.DataFrame) -> list[Signal]:
        if df.empty or "close" not in df.columns:
            return []

        rsi = df.get("rsi_14")
        bb_lower = df.get("bb_lower")

        if rsi is None or bb_lower is None:
            return []

        p7d = self.params["profit_7d"]
        p4w = self.params["profit_4w"]
        p_strong = self.params["profit_strong"]
        force_bars = self.params["force_close_dte"]  # ~90 trading days

        closes = df["close"].values
        signals = []
        in_position = False

        for i in range(1, len(df)):
            if in_position:
                continue  # one position at a time

            if pd.isna(rsi.iloc[i]) or pd.isna(bb_lower.iloc[i]):
                continue

            price = closes[i]

            # 开仓: RSI <= 40 且触碰布林带下轨
            if rsi.iloc[i] <= self.params["rsi_threshold"] and price <= bb_lower.iloc[i]:
                signals.append(Signal(
                    timestamp=df.index[i],
                    symbol="",
                    direction="long",
                    entry_price=price,
                    stop_loss=0,
                    strategy_name=self.name,
                    metadata={
                        "delta": self.params["delta_target"],
                        "type": "leaps_call",
                        "exit_rules": "7d:10% | 4w:20% | 100%:止盈 | 90DTE:强平",
                    },
                ))
                in_position = True

                # 向前扫描，找到第一个触发的出仓条件
                entry_price = price
                exit_idx = None
                exit_reason = "force_close"

                for j in range(i + 1, min(i + force_bars + 1, len(df))):
                    fwd_price = closes[j]
                    ret = (fwd_price - entry_price) / entry_price
                    bars_held = j - i

                    if ret >= p_strong:
                        exit_idx, exit_reason = j, f"强止盈 {p_strong*100:.0f}%"
                        break
                    if bars_held <= 7 and ret >= p7d:
                        exit_idx, exit_reason = j, f"7日止盈 {p7d*100:.0f}%"
                        break
                    if bars_held <= 28 and ret >= p4w:
                        exit_idx, exit_reason = j, f"4周止盈 {p4w*100:.0f}%"
                        break

                if exit_idx is None:
                    exit_idx = min(i + force_bars, len(df) - 1)

                signals.append(Signal(
                    timestamp=df.index[exit_idx],
                    symbol="",
                    direction="close",
                    entry_price=closes[exit_idx],
                    strategy_name=self.name,
                    metadata={"reason": exit_reason},
                ))
                in_position = False

        return signals
