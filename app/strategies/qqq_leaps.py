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
        # 止盈阶梯
        "profit_0_4m": 0.50,   # 0-4个月 50%
        "profit_4_6m": 0.30,   # 4-6个月 30%
        "profit_7_9m": 0.10,   # 7-9个月 10%
        "force_close_months": 9,  # >9个月强平
    }

    def generate_signals(self, df: pd.DataFrame) -> list[Signal]:
        if df.empty or "close" not in df.columns:
            return []

        signals = []
        returns = df.get("returns")
        if returns is None:
            return []

        open_count = 0

        for i in range(1, len(df)):
            if pd.isna(returns.iloc[i]):
                continue

            price = df["close"].iloc[i]

            # 开仓: 当日跌幅 > 1%
            if returns.iloc[i] <= self.params["dip_threshold"]:
                if open_count >= self.params["max_positions"]:
                    # 满 5 笔，先发出关闭最早的信号
                    signals.append(Signal(
                        timestamp=df.index[i],
                        symbol="QQQ",
                        direction="close",
                        entry_price=price,
                        strategy_name=self.name,
                        metadata={"reason": "持仓满5笔，清掉最早一笔", "type": "leaps_rotate"},
                    ))
                    open_count -= 1

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
                open_count += 1

        return signals
