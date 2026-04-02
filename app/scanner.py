"""
Goal-Driven Trading OS — Index Scanner
扫描 S&P 500 / NASDAQ 100 / Dow 30 成分股，用任意策略筛选买入信号

Usage:
    from scanner import scan_index, scan_symbols

    result = scan_index("sp500", "sma_crossover")
    for match in result["matches"]:
        print(match["symbol"], match["signal_direction"], match["risk_reward"])
"""
import time
import logging
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

import numpy as np
import pandas as pd
import yfinance as yf

from market_data import compute_technicals
from strategies.base import get_strategy, get_all_strategies, Signal

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Index constituent lists (top ~30 from each)
# ---------------------------------------------------------------------------

SP500_TOP: list[str] = [
    "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "BRK-B", "LLY", "AVGO", "JPM",
    "V", "UNH", "XOM", "MA", "PG", "COST", "HD", "JNJ", "ABBV", "WMT",
    "CRM", "MRK", "BAC", "ORCL", "CVX", "NFLX", "AMD", "PEP", "TMO", "LIN",
]

NASDAQ100_TOP: list[str] = [
    "AAPL", "MSFT", "NVDA", "AMZN", "META", "AVGO", "GOOGL", "COST", "TSLA", "NFLX",
    "AMD", "ADBE", "QCOM", "TXN", "AMGN", "INTU", "ISRG", "LRCX", "MU", "BKNG",
]

DOW30: list[str] = [
    "AAPL", "MSFT", "AMZN", "NVDA", "V", "UNH", "JNJ", "JPM", "PG", "HD",
    "MRK", "CVX", "KO", "DIS", "MCD", "CRM", "BA", "IBM", "GS", "CAT",
    "AXP", "MMM", "NKE", "WMT", "HON", "TRV", "CSCO", "VZ", "DOW", "INTC",
]

INDEX_MAP: dict[str, list[str]] = {
    "sp500": SP500_TOP,
    "nasdaq100": NASDAQ100_TOP,
    "dow30": DOW30,
}

# ---------------------------------------------------------------------------
# Cache — 15-minute TTL, keyed by (frozenset(symbols), strategy_name, params_key)
# ---------------------------------------------------------------------------

_scan_cache: dict[str, tuple[float, list[dict]]] = {}
_SCAN_CACHE_TTL = 900  # 15 minutes


def _cache_key(symbols: list[str], strategy_name: str, params: Optional[dict]) -> str:
    sym_key = ",".join(sorted(symbols))
    param_key = str(sorted(params.items())) if params else ""
    return f"{sym_key}|{strategy_name}|{param_key}"


# ---------------------------------------------------------------------------
# Batch download helper
# ---------------------------------------------------------------------------

def _batch_download(symbols: list[str], period: str = "3mo") -> dict[str, pd.DataFrame]:
    """
    Batch download OHLCV via yfinance.download (single HTTP call for all tickers).
    Returns {symbol: DataFrame} with lowercase columns.
    Falls back to individual downloads for any symbol that fails.
    """
    result: dict[str, pd.DataFrame] = {}
    if not symbols:
        return result

    try:
        raw = yf.download(
            symbols,
            period=period,
            group_by="ticker",
            threads=True,
            progress=False,
        )
    except Exception as exc:
        logger.warning("Batch download failed (%s), falling back to individual", exc)
        raw = pd.DataFrame()

    if raw.empty:
        # Fallback: download one-by-one with ThreadPool
        return _individual_download(symbols, period)

    # Single ticker edge case: yf.download returns flat columns instead of multi-level
    if len(symbols) == 1:
        sym = symbols[0]
        df = raw.copy()
        df.columns = [c.lower() if isinstance(c, str) else c for c in df.columns]
        if "close" in df.columns:
            df = df[["open", "high", "low", "close", "volume"]].dropna()
            df["returns"] = df["close"].pct_change()
            result[sym] = df
        return result

    for sym in symbols:
        try:
            if sym not in raw.columns.get_level_values(0):
                continue
            df = raw[sym].copy()
            df.columns = [c.lower() for c in df.columns]
            df = df[["open", "high", "low", "close", "volume"]].dropna()
            if df.empty or len(df) < 20:
                continue
            df["returns"] = df["close"].pct_change()
            result[sym] = df
        except Exception:
            continue

    # Fill gaps with individual download
    missing = [s for s in symbols if s not in result]
    if missing:
        result.update(_individual_download(missing, period))

    return result


def _individual_download(symbols: list[str], period: str) -> dict[str, pd.DataFrame]:
    """Download symbols one-by-one in parallel (fallback)."""
    result: dict[str, pd.DataFrame] = {}

    def _fetch_one(sym: str) -> tuple[str, Optional[pd.DataFrame]]:
        try:
            ticker = yf.Ticker(sym)
            df = ticker.history(period=period, auto_adjust=True)
            if df.empty or len(df) < 20:
                return sym, None
            df.columns = [c.lower() for c in df.columns]
            df = df[["open", "high", "low", "close", "volume"]].copy()
            df["returns"] = df["close"].pct_change()
            return sym, df
        except Exception:
            return sym, None

    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {pool.submit(_fetch_one, s): s for s in symbols}
        for fut in as_completed(futures):
            sym, df = fut.result()
            if df is not None and not df.empty:
                result[sym] = df

    return result


# ---------------------------------------------------------------------------
# Single-symbol analysis
# ---------------------------------------------------------------------------

def _analyze_symbol(
    symbol: str,
    df: pd.DataFrame,
    strategy_instance,
    lookback_days: int = 3,
) -> Optional[dict]:
    """
    Run strategy on one symbol's OHLCV data.
    Returns a match dict if the latest signal is a buy within `lookback_days`, else None.
    """
    try:
        df = compute_technicals(df)
    except Exception:
        return None

    if df.empty or len(df) < 30:
        return None

    try:
        signals: list[Signal] = strategy_instance.generate_signals(df)
    except Exception as exc:
        logger.debug("Strategy error for %s: %s", symbol, exc)
        return None

    if not signals:
        return None

    # Find the latest "long" (buy) signal within the lookback window
    cutoff = df.index[-1] - timedelta(days=lookback_days)
    recent_buys = [
        s for s in signals
        if s.direction == "long" and s.timestamp >= cutoff
    ]

    if not recent_buys:
        return None

    latest_signal = recent_buys[-1]
    latest = df.iloc[-1]
    price = float(latest["close"])
    atr = float(latest.get("atr_14", price * 0.02))
    rsi = float(latest.get("rsi_14", 50))

    # Compute trading parameters
    entry_price = float(latest_signal.entry_price)
    stop_loss = float(latest_signal.stop_loss) if latest_signal.stop_loss else price - atr * 2
    # Use take_profit from signal if set, otherwise default 3x ATR above entry
    target_price = (
        float(latest_signal.take_profit)
        if latest_signal.take_profit
        else price + atr * 3
    )

    risk = abs(price - stop_loss) if stop_loss else atr * 2
    reward = abs(target_price - price) if target_price else atr * 3
    risk_reward = round(reward / risk, 2) if risk > 0 else 0

    # Confidence / signal strength (0-100)
    confidence = latest_signal.confidence if latest_signal.confidence else 0.5
    signal_strength = int(min(100, confidence * 100))

    # Suggested position % of portfolio (based on risk)
    # Kelly-lite: cap at 5%, scale by confidence and R:R
    suggested_pct = min(5.0, round(confidence * min(risk_reward, 3) * 1.5, 1))

    # Days since signal
    days_since = (df.index[-1] - latest_signal.timestamp).days

    return {
        "symbol": symbol,
        "current_price": round(price, 2),
        "entry_zone": round(entry_price, 2),
        "stop_loss": round(stop_loss, 2),
        "target_price": round(target_price, 2),
        "risk_reward": risk_reward,
        "signal_strength": signal_strength,
        "suggested_position_pct": suggested_pct,
        "signal_direction": latest_signal.direction,
        "signal_date": latest_signal.timestamp.strftime("%Y-%m-%d"),
        "days_since_signal": days_since,
        "rsi": round(rsi, 1),
        "atr": round(atr, 2),
        "atr_pct": round(atr / price * 100, 2),
        "strategy_name": latest_signal.strategy_name or strategy_instance.name,
        "metadata": latest_signal.metadata or {},
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def scan_symbols(
    symbols: list[str],
    strategy_name: str,
    params: Optional[dict] = None,
) -> list[dict]:
    """
    Scan a list of symbols against a strategy.

    For each symbol: fetch 3-month history, compute technicals,
    run strategy.generate_signals(), check for recent buy signals.

    Returns list of match dicts sorted by signal_strength (desc).
    """
    # Check cache
    ck = _cache_key(symbols, strategy_name, params)
    now = time.time()
    if ck in _scan_cache:
        cached_ts, cached_result = _scan_cache[ck]
        if now - cached_ts < _SCAN_CACHE_TTL:
            return cached_result

    # Resolve strategy
    strategy_cls = get_strategy(strategy_name)
    if strategy_cls is None:
        raise ValueError(f"Unknown strategy: {strategy_name}. "
                         f"Available: {list(get_all_strategies().keys())}")
    strategy_instance = strategy_cls(params)

    # Batch download all symbols
    t0 = time.time()
    data = _batch_download(symbols, period="3mo")
    dl_time = time.time() - t0
    logger.info("Downloaded %d/%d symbols in %.1fs", len(data), len(symbols), dl_time)

    # Analyze each symbol (already have data, compute in-thread is fast)
    matches: list[dict] = []
    errors: list[str] = []

    for sym in symbols:
        if sym not in data:
            errors.append(sym)
            continue
        try:
            match = _analyze_symbol(sym, data[sym], strategy_instance)
            if match is not None:
                matches.append(match)
        except Exception as exc:
            logger.debug("Analysis error for %s: %s", sym, exc)
            errors.append(sym)

    # Sort by signal strength descending, then risk-reward
    matches.sort(key=lambda m: (m["signal_strength"], m["risk_reward"]), reverse=True)

    # Cache result
    _scan_cache[ck] = (now, matches)

    return matches


def scan_index(
    index_name: str,
    strategy_name: str,
    params: Optional[dict] = None,
) -> dict:
    """
    Scan an index (sp500 / nasdaq100 / dow30 / all) against a strategy.

    Returns:
        {
            "index": str,
            "strategy": str,
            "symbols_scanned": int,
            "matches": [...],
            "match_count": int,
            "scan_time_sec": float,
            "cached": bool,
        }
    """
    t0 = time.time()

    if index_name == "all":
        # Union of all indices, deduplicated
        symbols = list(set(SP500_TOP + NASDAQ100_TOP + DOW30))
    else:
        symbols = INDEX_MAP.get(index_name)
        if symbols is None:
            raise ValueError(
                f"Unknown index: {index_name}. "
                f"Available: {list(INDEX_MAP.keys()) + ['all']}"
            )

    # Check if result is cached
    ck = _cache_key(symbols, strategy_name, params)
    cached = ck in _scan_cache and (time.time() - _scan_cache[ck][0]) < _SCAN_CACHE_TTL

    matches = scan_symbols(symbols, strategy_name, params)
    elapsed = round(time.time() - t0, 2)

    return {
        "index": index_name,
        "strategy": strategy_name,
        "params": params or {},
        "symbols_scanned": len(symbols),
        "matches": matches,
        "match_count": len(matches),
        "scan_time_sec": elapsed,
        "cached": cached,
    }


def list_available_strategies() -> list[dict]:
    """Return metadata for all registered strategies (for UI dropdowns)."""
    result = []
    for name, cls in get_all_strategies().items():
        result.append({
            "name": name,
            "description": getattr(cls, "description", ""),
            "default_params": getattr(cls, "default_params", {}),
        })
    result.sort(key=lambda x: x["name"])
    return result


def list_available_indices() -> list[dict]:
    """Return metadata for all available indices (for UI dropdowns)."""
    return [
        {"key": "sp500", "name": "S&P 500 Top 30", "count": len(SP500_TOP)},
        {"key": "nasdaq100", "name": "NASDAQ 100 Top 20", "count": len(NASDAQ100_TOP)},
        {"key": "dow30", "name": "Dow Jones 30", "count": len(DOW30)},
        {"key": "all", "name": "All Indices (deduplicated)", "count": len(set(SP500_TOP + NASDAQ100_TOP + DOW30))},
    ]
