"""
QQQ LEAPS Call 策略
QQQ 日跌 1% 时买入一年期看涨期权 (delta 0.6)

开仓条件:
- QQQ 当日价格跌破 1%
- 买入 QQQ 一年左右的看涨期权
- 选行权价 delta 等于 0.6 左右的期权
- 单次用 20% 的仓位买入
- 上限持有 5 笔，出现新信号但满 5 笔，清掉最早的一笔

出仓条件:
- 前 0-4 个月，收益 > 50%
- 4-6 个月，收益 > 30%
- 7-9 个月，收益 > 10%
- > 9 个月，强制卖出（无论盈亏）
"""
import pandas as pd
from strategies.base import StrategyBase, Signal, register_strategy


@register_strategy
class QQQLeaps(StrategyBase):
    name = "qqq_leaps"
    description = "QQQ LEAPS：日跌 1% 时买入一年期 delta 0.6 Call"
    default_params = {
        "dip_threshold": -0.01,  # 日跌 1%
        "delta_target": 0.6,
        "position_pct": 0.20,
        "max_positions": 5,
        "dte_target": 365,  # 一年期
        # 止盈阶梯（用底层股票收益近似期权收益）
        "profit_0_4m": 0.50,   # 0-4个月 50%
        "profit_4_6m": 0.30,   # 4-6个月 30%
        "profit_7_9m": 0.10,   # 7-9个月 10%
        "force_close_months": 9,  # >9个月强平
    }

    def generate_signals(self, df: pd.DataFrame) -> list[Signal]:
        if df.empty or "close" not in df.columns:
            return []

        returns = df.get("returns")
        if returns is None:
            return []

        p_0_4m = self.params["profit_0_4m"]
        p_4_6m = self.params["profit_4_6m"]
        p_7_9m = self.params["profit_7_9m"]
        force_bars = int(self.params["force_close_months"] * 21)  # ~交易日

        closes = df["close"].values
        signals = []
        in_position = False

        for i in range(1, len(df)):
            if in_position:
                continue  # one position at a time (simplification)

            if pd.isna(returns.iloc[i]):
                continue

            price = closes[i]

            # 开仓: 当日跌幅 >= 阈值
            if returns.iloc[i] <= self.params["dip_threshold"]:
                signals.append(Signal(
                    timestamp=df.index[i],
                    symbol="QQQ",
                    direction="long",
                    entry_price=price,
                    stop_loss=0,
                    strategy_name=self.name,
                    metadata={
                        "delta": self.params["delta_target"],
                        "type": "leaps_call",
                        "dte": self.params["dte_target"],
                        "exit_rules": "0-4m:>50% | 4-6m:>30% | 7-9m:>10% | >9m:强平",
                        "trigger": f"QQQ 日跌 {returns.iloc[i]*100:.1f}%",
                    },
                ))
                in_position = True

                # 向前扫描出仓
                entry_price = price
                exit_idx = None
                exit_reason = "force_close"

                for j in range(i + 1, min(i + force_bars + 1, len(df))):
                    fwd_price = closes[j]
                    ret = (fwd_price - entry_price) / entry_price
                    bars_held = j - i

                    m4 = 4 * 21
                    m6 = 6 * 21

                    if bars_held <= m4 and ret >= p_0_4m:
                        exit_idx, exit_reason = j, f"0-4月止盈 {p_0_4m*100:.0f}%"
                        break
                    if m4 < bars_held <= m6 and ret >= p_4_6m:
                        exit_idx, exit_reason = j, f"4-6月止盈 {p_4_6m*100:.0f}%"
                        break
                    if bars_held > m6 and ret >= p_7_9m:
                        exit_idx, exit_reason = j, f"7-9月止盈 {p_7_9m*100:.0f}%"
                        break

                if exit_idx is None:
                    exit_idx = min(i + force_bars, len(df) - 1)

                signals.append(Signal(
                    timestamp=df.index[exit_idx],
                    symbol="QQQ",
                    direction="close",
                    entry_price=closes[exit_idx],
                    strategy_name=self.name,
                    metadata={"reason": exit_reason},
                ))
                in_position = False

        return signals
