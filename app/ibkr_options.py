"""
Goal-Driven Trading OS — IBKR Options Data
通过 ib_insync 获取实时期权链、Greeks、IV
"""
import os
import logging
from datetime import datetime, timedelta
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class OptionContract:
    """期权合约"""
    symbol: str
    strike: float
    expiry: str
    right: str  # P or C
    delta: float = 0
    gamma: float = 0
    theta: float = 0
    vega: float = 0
    iv: float = 0
    bid: float = 0
    ask: float = 0
    mid: float = 0
    volume: int = 0
    open_interest: int = 0
    dte: int = 0
    contract_code: str = ""


def fetch_ibkr_options_chain(symbol: str, right: str = "P", dte_min: int = 20, dte_max: int = 60) -> list[OptionContract]:
    """
    从 IBKR 获取期权链

    Args:
        symbol: 标的代码
        right: P (Put) or C (Call)
        dte_min: 最小到期天数
        dte_max: 最大到期天数

    Returns: list of OptionContract
    """
    try:
        from broker import get_ibkr_client
        client = get_ibkr_client()
        if not client:
            logger.info("IBKR not connected, falling back to yfinance")
            return _fetch_yfinance_options(symbol, right, dte_min, dte_max)

        from ib_insync import Stock, Option
        stock = Stock(symbol, "SMART", "USD")
        client.qualifyContracts(stock)

        chains = client.reqSecDefOptParams(stock.symbol, "", stock.secType, stock.conId)
        if not chains:
            return _fetch_yfinance_options(symbol, right, dte_min, dte_max)

        chain = chains[0]  # Use first exchange
        today = datetime.now()
        results = []

        for expiry in sorted(chain.expirations):
            exp_date = datetime.strptime(expiry, "%Y%m%d")
            dte = (exp_date - today).days
            if dte < dte_min or dte > dte_max:
                continue

            for strike in sorted(chain.strikes):
                contract = Option(symbol, expiry, strike, right, "SMART")
                try:
                    client.qualifyContracts(contract)
                    ticker = client.reqMktData(contract, "", False, False)
                    client.sleep(0.5)

                    bid = float(ticker.bid) if ticker.bid and ticker.bid > 0 else 0
                    ask = float(ticker.ask) if ticker.ask and ticker.ask > 0 else 0
                    mid = (bid + ask) / 2 if bid and ask else 0

                    # Request Greeks
                    greeks = ticker.modelGreeks
                    delta = float(greeks.delta) if greeks and greeks.delta else 0
                    gamma = float(greeks.gamma) if greeks and greeks.gamma else 0
                    theta = float(greeks.theta) if greeks and greeks.theta else 0
                    vega = float(greeks.vega) if greeks and greeks.vega else 0
                    iv = float(greeks.impliedVol) if greeks and greeks.impliedVol else 0

                    results.append(OptionContract(
                        symbol=symbol,
                        strike=strike,
                        expiry=expiry,
                        right=right,
                        delta=round(delta, 4),
                        gamma=round(gamma, 6),
                        theta=round(theta, 4),
                        vega=round(vega, 4),
                        iv=round(iv, 4),
                        bid=round(bid, 2),
                        ask=round(ask, 2),
                        mid=round(mid, 2),
                        dte=dte,
                        contract_code=f"US.{symbol}{expiry}{right}{int(strike*1000):08d}",
                    ))
                    client.cancelMktData(contract)
                except Exception:
                    continue

            if len(results) > 50:
                break

        return results

    except ImportError:
        return _fetch_yfinance_options(symbol, right, dte_min, dte_max)
    except Exception as e:
        logger.error(f"IBKR options fetch failed: {e}")
        return _fetch_yfinance_options(symbol, right, dte_min, dte_max)


def _fetch_yfinance_options(symbol: str, right: str = "P", dte_min: int = 20, dte_max: int = 60) -> list[OptionContract]:
    """yfinance 回退方案"""
    try:
        import yfinance as yf
        ticker = yf.Ticker(symbol)
        expirations = ticker.options
        if not expirations:
            return []

        today = datetime.now()
        results = []

        for exp_str in expirations[:3]:
            exp_date = datetime.strptime(exp_str, "%Y-%m-%d")
            dte = (exp_date - today).days
            if dte < dte_min or dte > dte_max:
                continue

            chain = ticker.option_chain(exp_str)
            options_df = chain.puts if right == "P" else chain.calls

            for _, row in options_df.iterrows():
                strike = float(row["strike"])
                bid = float(row.get("bid", 0))
                ask = float(row.get("ask", 0))
                iv = float(row.get("impliedVolatility", 0))
                vol = int(row.get("volume", 0)) if not pd.isna(row.get("volume")) else 0
                oi = int(row.get("openInterest", 0)) if not pd.isna(row.get("openInterest")) else 0

                results.append(OptionContract(
                    symbol=symbol,
                    strike=strike,
                    expiry=exp_str.replace("-", ""),
                    right=right,
                    iv=round(iv, 4),
                    bid=round(bid, 2),
                    ask=round(ask, 2),
                    mid=round((bid + ask) / 2, 2) if bid and ask else 0,
                    volume=vol,
                    open_interest=oi,
                    dte=dte,
                    contract_code=f"US.{symbol}{exp_str.replace('-', '')}{right}{int(strike*1000):08d}",
                ))

        return results
    except Exception as e:
        logger.error(f"yfinance options fallback failed: {e}")
        return []


def filter_options_for_sell_put(options: list[OptionContract], current_price: float,
                                 max_delta: float = 0.30, min_premium: float = 0.5) -> list[OptionContract]:
    """
    筛选适合 Sell Put 的合约

    条件：delta 绝对值 < max_delta, 权利金 > min_premium, 行权价 < 现价
    """
    filtered = []
    for opt in options:
        if opt.strike >= current_price:
            continue
        if abs(opt.delta) > max_delta and opt.delta != 0:
            continue
        if opt.mid < min_premium and opt.mid != 0:
            continue
        filtered.append(opt)

    filtered.sort(key=lambda x: abs(x.delta) if x.delta else 0.5)
    return filtered


# yfinance needs pandas
try:
    import pandas as pd
except ImportError:
    pass
