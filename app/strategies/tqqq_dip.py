"""
TQQQ 抄底策略
在 QQQ 趋势向上时，利用日内回调买入 TQQQ（3倍杠杆 QQQ）

开仓条件:
- QQQ 价格在 200 日移动平均线价格 4% 以上
- 单日回调超过 1%
- 使用仓位的 20% 买入 TQQQ

出仓条件:
- QQQ 价格在 200 日移动平均线价格以下 3%
- 全部清仓所有 TQQQ 仓位
"""
import pandas as pd
from strategies.base import StrategyBase, Signal, register_strategy


@register_strategy
class TQQQDip(StrategyBase):
    name = "tqqq_dip"
    description = "TQQQ 抄底：QQQ 趋势向上 + 日内回调 1% 时买入 3 倍杠杆"
    default_params = {
        "sma_200_above_pct": 0.04,   # QQQ 在 MA200 上方 4%
        "daily_dip_pct": -0.01,      # 单日回调 1%
        "position_pct": 0.20,        # 每次用 20% 仓位
        "exit_below_sma200_pct": -0.03,  # QQQ 跌破 MA200 下方 3% 清仓
    }

    def generate_signals(self, df: pd.DataFrame) -> list[Signal]:
        """注意：df 应该是 QQQ 的数据，但交易标的是 TQQQ"""
        if df.empty or "close" not in df.columns:
            return []

        signals = []
        sma_200 = df.get("sma_200")
        returns = df.get("returns")

        if sma_200 is None or returns is None:
            return []

        position_open = False

        for i in range(1, len(df)):
            if pd.isna(sma_200.iloc[i]) or pd.isna(returns.iloc[i]):
                continue

            price = df["close"].iloc[i]
            ma200 = sma_200.iloc[i]
            daily_return = returns.iloc[i]
            above_ma200_pct = (price - ma200) / ma200

            # 开仓: QQQ 在 MA200 上方 4% + 当日回调 > 1%
            if (not position_open
                and above_ma200_pct >= self.params["sma_200_above_pct"]
                and daily_return <= self.params["daily_dip_pct"]):
                signals.append(Signal(
                    timestamp=df.index[i],
                    symbol="TQQQ",  # 交易 TQQQ，但用 QQQ 数据判断
                    direction="long",
                    entry_price=price,
                    stop_loss=0,
                    strategy_name=self.name,
                    metadata={
                        "type": "leveraged_etf",
                        "trigger": f"QQQ 在 MA200 上方 {above_ma200_pct*100:.1f}%，日内回调 {daily_return*100:.1f}%",
                        "position_size": f"仓位 {self.params['position_pct']*100:.0f}%",
                    },
                ))
                position_open = True

            # 出仓: QQQ 跌破 MA200 下方 3%
            elif position_open and above_ma200_pct <= self.params["exit_below_sma200_pct"]:
                signals.append(Signal(
                    timestamp=df.index[i],
                    symbol="TQQQ",
                    direction="close",
                    entry_price=price,
                    strategy_name=self.name,
                    metadata={
                        "type": "leveraged_etf",
                        "trigger": f"QQQ 跌破 MA200 下方 {above_ma200_pct*100:.1f}%，全部清仓 TQQQ",
                    },
                ))
                position_open = False

        return signals
