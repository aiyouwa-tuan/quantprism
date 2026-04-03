"""
Goal-Driven Trading OS — Quantitative Analysis
Relative rotation, CAPM, Fama-French, ADF unit root test, rolling stats.
"""
import logging
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Relative Rotation Graph (RRG)
# ---------------------------------------------------------------------------

# Sector ETFs for rotation analysis
SECTOR_ETFS = {
    "XLK": "科技",
    "XLF": "金融",
    "XLE": "能源",
    "XLV": "医疗",
    "XLI": "工业",
    "XLY": "非必需消费",
    "XLP": "必需消费",
    "XLU": "公用事业",
    "XLRE": "房地产",
    "XLB": "材料",
    "XLC": "通信",
}

BENCHMARK = "SPY"


def compute_rs_ratio(symbol_prices: pd.Series, benchmark_prices: pd.Series, window: int = 52) -> pd.Series:
    """
    Compute JdK RS-Ratio: normalized relative strength vs benchmark.
    Both series should be weekly closing prices.
    RS-Ratio > 100 = outperforming, < 100 = underperforming.
    """
    if len(symbol_prices) < window + 1 or len(benchmark_prices) < window + 1:
        return pd.Series(dtype=float)

    rs = symbol_prices / benchmark_prices
    rs_sma = rs.rolling(window=10).mean()

    # Normalize to 100-based scale using 52-week rolling window
    rs_min = rs_sma.rolling(window=window).min()
    rs_max = rs_sma.rolling(window=window).max()
    denom = rs_max - rs_min
    denom = denom.replace(0, np.nan)
    rs_ratio = 100 + ((rs_sma - rs_min) / denom - 0.5) * 40
    return rs_ratio


def compute_rs_momentum(rs_ratio: pd.Series, momentum_window: int = 4) -> pd.Series:
    """
    Compute RS-Momentum: rate of change of RS-Ratio over momentum_window periods.
    RS-Momentum > 100 = accelerating, < 100 = decelerating.
    """
    if len(rs_ratio) < momentum_window + 1:
        return pd.Series(dtype=float)

    roc = rs_ratio.pct_change(periods=momentum_window) * 100
    rs_momentum = 100 + roc
    return rs_momentum


def compute_relative_rotation(benchmark_df: pd.DataFrame = None) -> list:
    """
    Compute relative rotation data for all sector ETFs vs SPY.
    Returns list of dicts ready for scatter plot rendering.

    Each dict: {symbol, name, rs_ratio, rs_momentum, quadrant}
    Quadrants: leading (high ratio, high mom), weakening (high ratio, low mom),
               lagging (low ratio, low mom), improving (low ratio, high mom)
    """
    from market_data import fetch_stock_history

    try:
        bench_df = fetch_stock_history(BENCHMARK, period="2y", interval="1wk")
        if bench_df.empty:
            return []
        bench_weekly = bench_df["close"]
    except Exception as e:
        logger.warning(f"compute_relative_rotation: benchmark fetch failed: {e}")
        return []

    results = []
    for symbol, name in SECTOR_ETFS.items():
        try:
            df = fetch_stock_history(symbol, period="2y", interval="1wk")
            if df.empty or len(df) < 60:
                continue

            prices = df["close"]
            aligned = pd.concat([prices, bench_weekly], axis=1, join="inner")
            aligned.columns = ["symbol", "bench"]

            rs_ratio = compute_rs_ratio(aligned["symbol"], aligned["bench"])
            rs_momentum = compute_rs_momentum(rs_ratio)

            current_ratio = float(rs_ratio.dropna().iloc[-1]) if not rs_ratio.dropna().empty else 100.0
            current_momentum = float(rs_momentum.dropna().iloc[-1]) if not rs_momentum.dropna().empty else 100.0

            if current_ratio >= 100 and current_momentum >= 100:
                quadrant = "leading"
            elif current_ratio >= 100 and current_momentum < 100:
                quadrant = "weakening"
            elif current_ratio < 100 and current_momentum < 100:
                quadrant = "lagging"
            else:
                quadrant = "improving"

            results.append({
                "symbol": symbol,
                "name": name,
                "rs_ratio": round(current_ratio, 2),
                "rs_momentum": round(current_momentum, 2),
                "quadrant": quadrant,
            })

        except Exception as e:
            logger.debug(f"compute_relative_rotation({symbol}): {e}")

    return results


# ---------------------------------------------------------------------------
# CAPM Analysis
# ---------------------------------------------------------------------------

def compute_capm(symbol: str, benchmark: str = "SPY", lookback_days: int = 252) -> dict:
    """
    Compute CAPM metrics: alpha, beta, R-squared, Sharpe ratio.
    Uses daily returns over lookback_days trading days.
    """
    from market_data import fetch_stock_history

    try:
        sym_df = fetch_stock_history(symbol, period="2y")
        bench_df = fetch_stock_history(benchmark, period="2y")

        if sym_df.empty or bench_df.empty:
            return {"error": "数据不足"}

        sym_returns = sym_df["returns"].dropna().tail(lookback_days)
        bench_returns = bench_df["returns"].dropna().tail(lookback_days)

        aligned = pd.concat([sym_returns, bench_returns], axis=1, join="inner")
        aligned.columns = ["sym", "bench"]
        aligned = aligned.dropna()

        if len(aligned) < 30:
            return {"error": "数据点不足"}

        # Risk-free rate: approximate 5% annual / 252 = daily
        rf_daily = 0.05 / 252

        sym_excess = aligned["sym"] - rf_daily
        bench_excess = aligned["bench"] - rf_daily

        # OLS: sym_excess = alpha + beta * bench_excess
        cov_matrix = np.cov(sym_excess, bench_excess)
        beta = cov_matrix[0, 1] / cov_matrix[1, 1]
        alpha_daily = sym_excess.mean() - beta * bench_excess.mean()
        alpha_annual = alpha_daily * 252

        # R-squared
        predicted = alpha_daily + beta * bench_excess
        ss_res = ((sym_excess - predicted) ** 2).sum()
        ss_tot = ((sym_excess - sym_excess.mean()) ** 2).sum()
        r_squared = 1 - ss_res / ss_tot if ss_tot > 0 else 0

        # Sharpe
        ann_return = sym_returns.mean() * 252
        ann_vol = sym_returns.std() * np.sqrt(252)
        sharpe = (ann_return - 0.05) / ann_vol if ann_vol > 0 else 0

        # Treynor
        treynor = (ann_return - 0.05) / beta if beta != 0 else 0

        return {
            "symbol": symbol,
            "benchmark": benchmark,
            "beta": round(float(beta), 3),
            "alpha_annual": round(float(alpha_annual) * 100, 2),  # as %
            "r_squared": round(float(r_squared), 3),
            "annual_return": round(float(ann_return) * 100, 2),
            "annual_vol": round(float(ann_vol) * 100, 2),
            "sharpe": round(float(sharpe), 3),
            "treynor": round(float(treynor), 4),
            "observations": len(aligned),
        }

    except Exception as e:
        logger.warning(f"compute_capm({symbol}): {e}")
        return {"error": str(e)}


def compute_fama_french(symbol: str, lookback_days: int = 252) -> dict:
    """
    Compute Fama-French 3-factor model: alpha, beta_mkt, beta_smb, beta_hml.
    Falls back to CAPM if FF data unavailable.
    """
    from data_providers import fetch_fama_french_factors
    from market_data import fetch_stock_history

    ff_data = fetch_fama_french_factors()
    if ff_data is None:
        return compute_capm(symbol, lookback_days=lookback_days)

    try:
        sym_df = fetch_stock_history(symbol, period="2y")
        if sym_df.empty:
            return {"error": "数据不足"}

        sym_returns = sym_df["returns"].dropna()

        # Align with FF data
        aligned = pd.concat([sym_returns, ff_data], axis=1, join="inner")
        aligned = aligned.dropna().tail(lookback_days)

        if len(aligned) < 30:
            return compute_capm(symbol, lookback_days=lookback_days)

        y = aligned.iloc[:, 0] - aligned["RF"]  # excess returns
        X = aligned[["Mkt-RF", "SMB", "HML"]]
        X = pd.concat([pd.Series(1, index=X.index, name="const"), X], axis=1)

        # OLS
        XtX = X.T @ X
        Xty = X.T @ y
        coeffs = np.linalg.lstsq(XtX, Xty, rcond=None)[0]

        alpha_daily, beta_mkt, beta_smb, beta_hml = coeffs
        alpha_annual = alpha_daily * 252

        # R-squared
        predicted = X @ coeffs
        ss_res = ((y - predicted) ** 2).sum()
        ss_tot = ((y - y.mean()) ** 2).sum()
        r_squared = 1 - ss_res / ss_tot if ss_tot > 0 else 0

        ann_return = sym_returns.mean() * 252
        ann_vol = sym_returns.std() * np.sqrt(252)
        sharpe = (ann_return - 0.05) / ann_vol if ann_vol > 0 else 0

        return {
            "symbol": symbol,
            "model": "fama_french_3",
            "alpha_annual": round(float(alpha_annual) * 100, 2),
            "beta_mkt": round(float(beta_mkt), 3),
            "beta_smb": round(float(beta_smb), 3),
            "beta_hml": round(float(beta_hml), 3),
            "r_squared": round(float(r_squared), 3),
            "annual_return": round(float(ann_return) * 100, 2),
            "annual_vol": round(float(ann_vol) * 100, 2),
            "sharpe": round(float(sharpe), 3),
            "observations": len(aligned),
        }

    except Exception as e:
        logger.warning(f"compute_fama_french({symbol}): {e}")
        return compute_capm(symbol, lookback_days=lookback_days)


# ---------------------------------------------------------------------------
# ADF Unit Root Test
# ---------------------------------------------------------------------------

def adf_test(prices: pd.Series) -> dict:
    """
    Augmented Dickey-Fuller test for stationarity.
    Returns {stationary, adf_stat, p_value, critical_values, interpretation}.
    Falls back gracefully if statsmodels not installed.
    """
    try:
        from statsmodels.tsa.stattools import adfuller
    except ImportError:
        return {"error": "statsmodels not installed", "stationary": None}

    try:
        prices_clean = prices.dropna()
        if len(prices_clean) < 20:
            return {"error": "数据点不足", "stationary": None}

        result = adfuller(prices_clean, autolag="AIC")
        adf_stat = float(result[0])
        p_value = float(result[1])
        critical_values = {k: round(float(v), 3) for k, v in result[4].items()}
        stationary = p_value < 0.05

        return {
            "stationary": stationary,
            "adf_stat": round(adf_stat, 4),
            "p_value": round(p_value, 4),
            "critical_values": critical_values,
            "interpretation": "平稳序列（均值回归特性）" if stationary else "非平稳序列（趋势性）",
        }

    except Exception as e:
        return {"error": str(e), "stationary": None}


# ---------------------------------------------------------------------------
# Rolling Statistics
# ---------------------------------------------------------------------------

def compute_rolling_stats(symbol: str, window: int = 20) -> dict:
    """
    Compute rolling correlation, beta, and volatility vs SPY.
    Returns {rolling_beta, rolling_corr, rolling_vol} as latest values.
    """
    from market_data import fetch_stock_history

    try:
        sym_df = fetch_stock_history(symbol, period="1y")
        bench_df = fetch_stock_history("SPY", period="1y")

        if sym_df.empty or bench_df.empty:
            return {}

        sym_r = sym_df["returns"].dropna()
        bench_r = bench_df["returns"].dropna()

        aligned = pd.concat([sym_r, bench_r], axis=1, join="inner").dropna()
        aligned.columns = ["sym", "bench"]

        if len(aligned) < window + 1:
            return {}

        # Rolling correlation
        rolling_corr = aligned["sym"].rolling(window).corr(aligned["bench"])

        # Rolling beta
        def _roll_beta(sub):
            cov = np.cov(sub["sym"], sub["bench"])
            return cov[0, 1] / cov[1, 1] if cov[1, 1] != 0 else np.nan

        rolling_beta_vals = []
        for i in range(window, len(aligned) + 1):
            sub = aligned.iloc[i - window:i]
            rolling_beta_vals.append(_roll_beta(sub))
        rolling_beta = pd.Series(rolling_beta_vals, index=aligned.index[window - 1:])

        # Rolling volatility (annualized)
        rolling_vol = aligned["sym"].rolling(window).std() * np.sqrt(252)

        return {
            "rolling_beta": round(float(rolling_beta.dropna().iloc[-1]), 3) if not rolling_beta.dropna().empty else None,
            "rolling_corr": round(float(rolling_corr.dropna().iloc[-1]), 3) if not rolling_corr.dropna().empty else None,
            "rolling_vol": round(float(rolling_vol.dropna().iloc[-1]) * 100, 2) if not rolling_vol.dropna().empty else None,
            "window": window,
        }

    except Exception as e:
        logger.warning(f"compute_rolling_stats({symbol}): {e}")
        return {}
