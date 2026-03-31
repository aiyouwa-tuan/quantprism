"""
Black-Scholes 期权定价模块 (V20: 含波动率偏斜)
用于从历史数据模拟期权价格
"""
import numpy as np
from scipy.stats import norm
import config as cfg


def bs_price(S, K, T, r, sigma, option_type="put"):
    """
    Black-Scholes 期权定价
    S: 标的价格
    K: 行权价
    T: 到期时间（年）
    r: 无风险利率
    sigma: 波动率
    option_type: "call" 或 "put"
    """
    if T <= 0:
        if option_type == "call":
            return max(S - K, 0)
        else:
            return max(K - S, 0)

    d1 = (np.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * np.sqrt(T))
    d2 = d1 - sigma * np.sqrt(T)

    if option_type == "call":
        return S * norm.cdf(d1) - K * np.exp(-r * T) * norm.cdf(d2)
    else:
        return K * np.exp(-r * T) * norm.cdf(-d2) - S * norm.cdf(-d1)


def bs_delta(S, K, T, r, sigma, option_type="put"):
    """
    Black-Scholes Delta
    """
    if T <= 0:
        if option_type == "call":
            return 1.0 if S > K else 0.0
        else:
            return -1.0 if S < K else 0.0

    d1 = (np.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * np.sqrt(T))

    if option_type == "call":
        return norm.cdf(d1)
    else:
        return norm.cdf(d1) - 1.0


def find_strike_by_delta(S, T, r, sigma, target_delta, option_type="put",
                          strike_step=1.0):
    """
    根据目标 delta 找到最近的行权价
    对于 Put，target_delta 应为负数的绝对值（如 0.15 表示 delta = -0.15）
    """
    if option_type == "put":
        target_delta = -abs(target_delta)

    best_strike = S
    best_diff = float("inf")

    # 搜索范围：标的价格 ±30%
    low = S * 0.70
    high = S * 1.30

    strike = low
    while strike <= high:
        d = bs_delta(S, strike, T, r, sigma, option_type)
        diff = abs(d - target_delta)
        if diff < best_diff:
            best_diff = diff
            best_strike = strike
        strike += strike_step

    # 对齐到 strike_step
    best_strike = round(best_strike / strike_step) * strike_step
    return best_strike


def apply_iv_skew(sigma, option_type):
    """
    应用波动率偏斜 (Volatility Skew)
    真实市场中 OTM Put 的 IV 比 ATM 高 15-25%（波动率微笑/偏斜）
    OTM Call 的 IV 比 ATM 略低
    """
    skew_put = getattr(cfg, 'IV_SKEW_PUT', 1.0)
    skew_call = getattr(cfg, 'IV_SKEW_CALL', 1.0)
    if option_type == "put":
        return sigma * skew_put
    else:
        return sigma * skew_call


def calc_friction_cost(vix):
    """
    计算整个 Iron Condor 组合单的摩擦成本，单位：$/股
    这是组合单的成本，不是单条腿的成本
    SPY IC 组合 bid-ask 约 $0.03-$0.06，高波动时更宽
    """
    half_spread = getattr(cfg, 'BID_ASK_HALF_SPREAD', 0.0)
    crisis_mult = getattr(cfg, 'BID_ASK_CRISIS_MULT', 1.0)
    crisis_vix = getattr(cfg, 'BID_ASK_CRISIS_VIX', 999)
    slippage = getattr(cfg, 'SLIPPAGE', 0.0)

    if vix > crisis_vix:
        half_spread *= crisis_mult

    return half_spread + slippage


def spread_value(S, K_short, K_long, T, r, sigma):
    """
    计算 Bull Put Spread 的净权利金（收入）
    卖出较高行权价 Put（K_short），买入较低行权价 Put（K_long）
    K_short > K_long
    收入 = 卖 Put 价格 - 买 Put 价格
    """
    short_put = bs_price(S, K_short, T, r, sigma, "put")
    long_put = bs_price(S, K_long, T, r, sigma, "put")
    return short_put - long_put


def bear_call_spread_value(S, K_short_call, K_long_call, T, r, sigma):
    """
    Bear Call Spread 净权利金
    卖出较低行权价 Call（K_short_call），买入较高行权价 Call（K_long_call）
    K_short_call < K_long_call
    收入 = 卖 Call 价格 - 买 Call 价格
    """
    short_call = bs_price(S, K_short_call, T, r, sigma, "call")
    long_call = bs_price(S, K_long_call, T, r, sigma, "call")
    return short_call - long_call


def spread_pnl_at_expiry(S_expiry, K_short, K_long, premium_received):
    """
    到期时 Bull Put Spread 的盈亏
    """
    short_put_value = max(K_short - S_expiry, 0)
    long_put_value = max(K_long - S_expiry, 0)
    intrinsic_loss = short_put_value - long_put_value  # 我方净亏损
    return premium_received - intrinsic_loss
