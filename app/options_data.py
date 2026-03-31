"""
Goal-Driven Trading OS — Options Data
yfinance options chain + Black-Scholes Greeks (reuses existing pricing.py)
"""
import sys
import os
import logging
import pandas as pd
import numpy as np
from datetime import datetime

logger = logging.getLogger(__name__)

# Import pricing functions from existing options-premium module
_PRICING_DIR = os.path.join(os.path.dirname(__file__), "..", "04-strategies", "options-premium")
if os.path.isdir(_PRICING_DIR) and _PRICING_DIR not in sys.path:
    sys.path.insert(0, _PRICING_DIR)

try:
    from pricing import bs_price, bs_delta
    HAS_PRICING = True
except ImportError:
    HAS_PRICING = False
    logger.warning("pricing.py not available, Greeks calculation disabled")


def fetch_options_chain(symbol: str, expiry: str = None) -> dict:
    """
    获取期权链

    Returns: {expirations: [...], calls: DataFrame, puts: DataFrame}
    """
    try:
        import yfinance as yf
        ticker = yf.Ticker(symbol)
        expirations = ticker.options

        if not expirations:
            return {"expirations": [], "calls": pd.DataFrame(), "puts": pd.DataFrame()}

        target_expiry = expiry if expiry and expiry in expirations else expirations[0]
        chain = ticker.option_chain(target_expiry)

        return {
            "expirations": list(expirations),
            "selected_expiry": target_expiry,
            "calls": chain.calls,
            "puts": chain.puts,
        }
    except Exception as e:
        logger.error(f"Options chain fetch failed for {symbol}: {e}")
        return {"expirations": [], "calls": pd.DataFrame(), "puts": pd.DataFrame(), "error": str(e)}


def compute_greeks(S: float, K: float, T: float, r: float, sigma: float, option_type: str = "call") -> dict:
    """
    计算期权 Greeks

    S: 标的价格, K: 行权价, T: 到期时间(年), r: 无风险利率, sigma: 波动率
    """
    if not HAS_PRICING:
        return {"error": "Pricing module not available"}

    try:
        price = bs_price(S, K, T, r, sigma, option_type)
        delta = bs_delta(S, K, T, r, sigma, option_type)

        # Gamma: d(delta)/d(S) via numerical differentiation
        ds = S * 0.01
        delta_up = bs_delta(S + ds, K, T, r, sigma, option_type)
        gamma = (delta_up - delta) / ds

        # Theta: d(price)/d(T) via numerical differentiation
        dt = 1 / 365
        if T > dt:
            price_later = bs_price(S, K, T - dt, r, sigma, option_type)
            theta = (price_later - price)  # daily theta (negative = time decay)
        else:
            theta = 0

        # Vega: d(price)/d(sigma)
        dsig = 0.01
        price_vol_up = bs_price(S, K, T, r, sigma + dsig, option_type)
        vega = (price_vol_up - price) / dsig * 0.01  # per 1% vol change

        return {
            "price": round(price, 4),
            "delta": round(delta, 4),
            "gamma": round(gamma, 6),
            "theta": round(theta, 4),
            "vega": round(vega, 4),
        }
    except Exception as e:
        return {"error": str(e)}
