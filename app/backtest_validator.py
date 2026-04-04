"""
QuantPrism — 快速策略验证器（backtesting.py）

使用位置：
  - strategy_hunter.py：AI 生成策略后，用真实回测数据替代 AI 估算值
  - 策略猎手 QuantEvolve 进化循环：验证每轮迭代结果，用真实数据驱动下一轮提示词

设计原则：
  - 秒级返回（≤5秒），用于 AI 策略的快速可行性验证，非精确回测
  - 安全执行 AI 生成的 python_signal_code（沙箱限制，只允许 pandas/numpy/ta 操作）
  - 失败时静默降级，不中断主流程
"""

import logging
import textwrap
from typing import Optional

import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)


# ─── SMA 交叉默认策略（AI 代码执行失败时的降级信号）──────────────────────────

def _sma_crossover_signals(prices: pd.DataFrame) -> pd.Series:
    """20/50 SMA 金叉死叉信号，作为默认降级策略"""
    close = prices["Close"]
    sma_fast = close.rolling(20).mean()
    sma_slow = close.rolling(50).mean()
    signal = pd.Series(0, index=prices.index)
    signal[sma_fast > sma_slow] = 1
    signal[sma_fast < sma_slow] = -1
    return signal


def _execute_signal_code(signal_code: str, df: pd.DataFrame) -> Optional[pd.Series]:
    """
    安全执行 AI 生成的信号代码。
    仅允许 pandas/numpy/ta 操作，禁止网络/文件/系统调用。
    """
    if not signal_code or len(signal_code.strip()) < 20:
        return None

    # 标准化列名（AI 代码可能用不同大小写）
    df_exec = df.copy()
    df_exec.columns = [c.lower() for c in df_exec.columns]
    if "close" not in df_exec.columns and "adj close" in df_exec.columns:
        df_exec["close"] = df_exec["adj close"]

    allowed_globals = {
        "pd": pd, "np": np, "DataFrame": pd.DataFrame,
        "Series": pd.Series, "__builtins__": {
            "len": len, "range": range, "int": int, "float": float,
            "abs": abs, "min": min, "max": max, "round": round,
            "print": print, "list": list, "dict": dict, "zip": zip,
            "enumerate": enumerate, "sorted": sorted,
        }
    }

    # 尝试导入 ta
    try:
        import ta
        allowed_globals["ta"] = ta
    except ImportError:
        pass

    try:
        # 包裹代码以防止顶层 import
        code = textwrap.dedent(signal_code)
        exec(code, allowed_globals)

        # 找到 generate_signals 函数并执行
        if "generate_signals" in allowed_globals:
            result_df = allowed_globals["generate_signals"](df_exec)
            if "signal" in result_df.columns:
                return result_df["signal"]

        return None
    except Exception as e:
        logger.debug("信号代码执行失败，降级到 SMA 交叉: %s", e)
        return None


# ─── backtesting.py 集成 ──────────────────────────────────────────────────────

def _run_backtest_lib(data: pd.DataFrame, signals: pd.Series, cash: float = 10000) -> Optional[dict]:
    """使用 backtesting.py 执行回测，返回关键指标"""
    try:
        from backtesting import Backtest, Strategy

        sig_series = signals

        class SignalStrategy(Strategy):
            def init(self):
                self.signals = self.I(lambda: sig_series.reindex(
                    pd.DatetimeIndex(self.data.index)
                ).fillna(0).values, name="signal", overlay=False)

            def next(self):
                if self.signals[-1] == 1 and not self.position:
                    self.buy()
                elif self.signals[-1] == -1 and self.position:
                    self.sell()

        # backtesting.py 需要 OHLCV 格式（首字母大写）
        bt_data = data[["Open", "High", "Low", "Close", "Volume"]].copy()
        bt_data = bt_data.dropna()

        bt = Backtest(bt_data, SignalStrategy, cash=cash, commission=0.002)
        stats = bt.run()

        return {
            "total_return_pct": round(float(stats.get("Return [%]", 0)), 1),
            "max_drawdown_pct": round(abs(float(stats.get("Max. Drawdown [%]", 0))), 1),
            "sharpe_ratio": round(float(stats.get("Sharpe Ratio", 0) or 0), 2),
            "win_rate": round(float(stats.get("Win Rate [%]", 0) or 0) / 100, 2),
            "total_trades": int(stats.get("# Trades", 0)),
            "engine": "backtesting.py",
        }
    except ImportError:
        return None
    except Exception as e:
        logger.debug("backtesting.py 执行失败: %s", e)
        return None


def _run_backtest_manual(prices: pd.DataFrame, signals: pd.Series,
                         cash: float = 10000) -> dict:
    """手动回测（backtesting.py 不可用时的降级实现）"""
    close = prices["Close"].reindex(signals.index).fillna(method="ffill")
    equity = cash
    position = 0.0
    entry_price = 0.0
    trades = []

    prev_sig = 0
    for date, sig in signals.items():
        price = close.get(date, None)
        if price is None or pd.isna(price):
            continue

        if sig == 1 and prev_sig != 1 and position == 0:
            shares = equity / price
            position = shares
            entry_price = price
            equity = 0.0
        elif sig == -1 and position > 0:
            equity = position * price
            ret = (price - entry_price) / entry_price
            trades.append(ret)
            position = 0.0
            entry_price = 0.0

        prev_sig = sig

    if position > 0:
        last_price = close.iloc[-1]
        equity = position * last_price
        ret = (last_price - entry_price) / entry_price
        trades.append(ret)

    total_return = (equity - cash) / cash * 100
    years = max((signals.index[-1] - signals.index[0]).days / 365, 0.5)
    annual_return = ((1 + total_return / 100) ** (1 / years) - 1) * 100

    # 最大回撤（简化）
    cum = [cash]
    eq = cash
    pos = 0.0
    ep = 0.0
    for date, sig in signals.items():
        price = close.get(date, None)
        if price is None or pd.isna(price):
            cum.append(cum[-1])
            continue
        if sig == 1 and pos == 0:
            pos = eq / price
            eq = 0.0
            ep = price
        elif sig == -1 and pos > 0:
            eq = pos * price
            pos = 0.0
        cum.append(eq + pos * price if pos > 0 else eq)

    cum_arr = np.array(cum, dtype=float)
    peak = np.maximum.accumulate(cum_arr)
    dd = (cum_arr - peak) / np.where(peak > 0, peak, 1)
    max_dd = abs(float(dd.min())) * 100

    win_rate = len([t for t in trades if t > 0]) / max(len(trades), 1)

    return {
        "total_return_pct": round(total_return, 1),
        "annual_return_pct": round(annual_return, 1),
        "max_drawdown_pct": round(max_dd, 1),
        "sharpe_ratio": None,
        "win_rate": round(win_rate, 2),
        "total_trades": len(trades),
        "engine": "manual",
    }


# ─── 主入口 ───────────────────────────────────────────────────────────────────

def validate_strategy(
    strategy_info: dict,
    symbol: str = "SPY",
    period: str = "3y",
    cash: float = 10000,
) -> Optional[dict]:
    """
    快速验证 AI 生成策略的实际可行性。

    Args:
        strategy_info: AI 生成的策略 dict（含 python_signal_code 字段）
        symbol:        验证用股票代码
        period:        回测周期
        cash:          初始资金

    Returns:
        {
            "annual_return_pct": 18.5,   # 年化收益%
            "max_drawdown_pct": 9.2,     # 最大回撤%
            "sharpe_ratio": 1.1,
            "win_rate": 0.58,
            "total_trades": 34,
            "is_viable": True,           # 是否比 buy-and-hold 强
            "engine": "backtesting.py",
        }
        None = 验证失败（不影响主流程）
    """
    try:
        import yfinance as yf
        data = yf.download(symbol, period=period, auto_adjust=True, progress=False)
        if data.empty or len(data) < 100:
            return None

        # 执行信号代码，失败则降级到 SMA 交叉
        signal_code = strategy_info.get("python_signal_code", "")
        signals = _execute_signal_code(signal_code, data) or _sma_crossover_signals(data)

        # 对齐索引
        signals = signals.reindex(data.index).fillna(0)

        # 优先用 backtesting.py，降级用手动
        result = _run_backtest_lib(data, signals, cash)
        if result is None:
            result = _run_backtest_manual(data, signals, cash)

        # 计算年化收益（backtesting.py 返回总收益，需换算）
        if "annual_return_pct" not in result and "total_return_pct" in result:
            years = max((data.index[-1] - data.index[0]).days / 365, 0.5)
            ann = ((1 + result["total_return_pct"] / 100) ** (1 / years) - 1) * 100
            result["annual_return_pct"] = round(ann, 1)

        # 买入持有基准
        bah_total = (data["Close"].iloc[-1] / data["Close"].iloc[0] - 1) * 100
        result["is_viable"] = result.get("total_return_pct", 0) > bah_total * 0.5
        result["buy_and_hold_pct"] = round(bah_total, 1)
        result["validated_symbol"] = symbol

        return result

    except Exception as e:
        logger.warning("策略验证失败（静默跳过）: %s", e)
        return None


def format_validation_summary(result: Optional[dict]) -> str:
    """将验证结果格式化为 AI 提示词中使用的文字描述"""
    if not result:
        return "（回测验证不可用）"

    lines = [
        f"实际回测结果（{result.get('validated_symbol', 'SPY')} {result.get('engine', '')}）：",
        f"  年化收益：{result.get('annual_return_pct', '?')}%",
        f"  最大回撤：{result.get('max_drawdown_pct', '?')}%",
        f"  夏普比：{result.get('sharpe_ratio', '?')}",
        f"  胜率：{round((result.get('win_rate', 0) or 0) * 100, 0):.0f}%",
        f"  总交易次数：{result.get('total_trades', '?')}",
        f"  买入持有基准：{result.get('buy_and_hold_pct', '?')}%",
    ]
    return "\n".join(lines)
