"""
Goal-Driven Trading OS — Data Providers
Fundamentals (yfinance), Macro (FRED), News (Finnhub)
with caching, retry, and rate limiting.
"""
import os
import json
import time
import logging
import threading
import zipfile
import io
from datetime import datetime, timedelta
from typing import Optional

import httpx
import yfinance as yf

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Cache store: {key: (fetched_at_timestamp, data)}
# ---------------------------------------------------------------------------
_cache: dict = {}
_cache_lock = threading.Lock()

TTL_FUNDAMENTALS = 86400      # 24h
TTL_MACRO = 3600              # 1h
TTL_NEWS = 900                # 15min
TTL_FAMA_FRENCH = 2592000     # 30 days

# ---------------------------------------------------------------------------
# Finnhub token bucket (50 calls/min)
# ---------------------------------------------------------------------------
_finnhub_lock = threading.Lock()
_finnhub_tokens = 50.0
_finnhub_last_refill = time.monotonic()
_FINNHUB_RATE = 50.0   # tokens per minute
_FINNHUB_CAPACITY = 50.0


def _finnhub_acquire():
    """Block until a Finnhub token is available."""
    global _finnhub_tokens, _finnhub_last_refill
    with _finnhub_lock:
        now = time.monotonic()
        elapsed = now - _finnhub_last_refill
        _finnhub_tokens = min(_FINNHUB_CAPACITY, _finnhub_tokens + elapsed * _FINNHUB_RATE / 60.0)
        _finnhub_last_refill = now
        if _finnhub_tokens < 1.0:
            sleep_time = (1.0 - _finnhub_tokens) * 60.0 / _FINNHUB_RATE
            time.sleep(sleep_time)
            _finnhub_tokens = 0.0
        else:
            _finnhub_tokens -= 1.0


# ---------------------------------------------------------------------------
# Cache helpers
# ---------------------------------------------------------------------------
def _cache_get(key: str, ttl: int):
    with _cache_lock:
        entry = _cache.get(key)
        if entry:
            fetched_at, data = entry
            if time.time() - fetched_at < ttl:
                return data
            del _cache[key]
    return None


def _cache_set(key: str, data):
    with _cache_lock:
        _cache[key] = (time.time(), data)


# ---------------------------------------------------------------------------
# Retry helper
# ---------------------------------------------------------------------------
def _retry(fn, retries: int = 2, backoff: tuple = (1, 3)):
    last_exc = None
    for attempt in range(retries + 1):
        try:
            return fn()
        except Exception as e:
            last_exc = e
            if attempt < retries:
                time.sleep(backoff[min(attempt, len(backoff) - 1)])
    raise last_exc


# ---------------------------------------------------------------------------
# Fundamentals (yfinance .info + .financials)
# ---------------------------------------------------------------------------
def fetch_fundamentals(symbol: str) -> dict:
    """
    Fetch fundamental data for a symbol.
    Returns dict with PE ratio, EPS, market cap, analyst ratings, earnings date, etc.
    Cached 24h. Falls back to empty dict on error.
    """
    key = f"fundamentals:{symbol.upper()}"
    cached = _cache_get(key, TTL_FUNDAMENTALS)
    if cached is not None:
        return cached

    def _fetch():
        ticker = yf.Ticker(symbol)
        info = ticker.info or {}

        # Extract earnings date
        earnings_date = None
        try:
            ed = ticker.earnings_dates
            if ed is not None and not ed.empty:
                future = ed[ed.index > datetime.now()]
                if not future.empty:
                    earnings_date = future.index[0].strftime("%Y-%m-%d")
        except Exception:
            pass

        # Revenue / net income from financials
        revenue = None
        net_income = None
        try:
            fin = ticker.financials
            if fin is not None and not fin.empty:
                if "Total Revenue" in fin.index:
                    revenue = float(fin.loc["Total Revenue"].iloc[0])
                if "Net Income" in fin.index:
                    net_income = float(fin.loc["Net Income"].iloc[0])
        except Exception:
            pass

        result = {
            "symbol": symbol.upper(),
            "pe_ratio": info.get("trailingPE") or info.get("forwardPE"),
            "eps": info.get("trailingEps"),
            "market_cap": info.get("marketCap"),
            "revenue": revenue or info.get("totalRevenue"),
            "net_income": net_income,
            "dividend_yield": info.get("trailingAnnualDividendYield") or info.get("dividendYield"),
            "analyst_target": info.get("targetMeanPrice"),
            "analyst_rating": info.get("recommendationKey", "").replace("_", " ").title() or None,
            "sector": info.get("sector"),
            "industry": info.get("industry"),
            "earnings_date": earnings_date,
            "week_52_high": info.get("fiftyTwoWeekHigh"),
            "week_52_low": info.get("fiftyTwoWeekLow"),
            "shares_outstanding": info.get("sharesOutstanding"),
            "free_cash_flow": info.get("freeCashflow"),
            "debt_to_equity": info.get("debtToEquity"),
            "return_on_equity": info.get("returnOnEquity"),
            "profit_margins": info.get("profitMargins"),
            "beta": info.get("beta"),
            "short_ratio": info.get("shortRatio"),
        }
        return result

    try:
        result = _retry(_fetch, retries=2, backoff=(1, 3))
        _cache_set(key, result)
        return result
    except Exception as e:
        logger.warning(f"fetch_fundamentals({symbol}) failed: {e}")
        stale = _cache_get(key, ttl=86400 * 7)  # serve up to 7-day stale
        return stale if stale else {"symbol": symbol.upper(), "error": str(e)}


# ---------------------------------------------------------------------------
# News (Finnhub)
# ---------------------------------------------------------------------------
def fetch_news(symbol: str, limit: int = 10) -> list:
    """
    Fetch recent news articles for a symbol from Finnhub.
    Cached 15min. Falls back to empty list if no API key.
    """
    api_key = os.getenv("FINNHUB_API_KEY")
    if not api_key:
        return []

    key = f"news:{symbol.upper()}"
    cached = _cache_get(key, TTL_NEWS)
    if cached is not None:
        return cached

    def _fetch():
        _finnhub_acquire()
        now = datetime.now()
        from_date = (now - timedelta(days=7)).strftime("%Y-%m-%d")
        to_date = now.strftime("%Y-%m-%d")

        resp = httpx.get(
            "https://finnhub.io/api/v1/company-news",
            params={
                "symbol": symbol.upper(),
                "from": from_date,
                "to": to_date,
                "token": api_key,
            },
            timeout=10,
        )
        resp.raise_for_status()
        articles = resp.json()

        result = []
        for art in articles[:limit]:
            result.append({
                "title": art.get("headline", ""),
                "source": art.get("source", ""),
                "url": art.get("url", ""),
                "published": datetime.fromtimestamp(art.get("datetime", 0)).isoformat() + "Z",
                "summary": art.get("summary", ""),
            })
        return result

    try:
        result = _retry(_fetch, retries=2, backoff=(1, 3))
        _cache_set(key, result)
        return result
    except Exception as e:
        logger.warning(f"fetch_news({symbol}) failed: {e}")
        stale = _cache_get(key, ttl=TTL_NEWS * 4)
        return stale if stale else []


# ---------------------------------------------------------------------------
# Macro data (FRED)
# ---------------------------------------------------------------------------
FRED_SERIES = {
    "gdp": "GDP",          # Gross Domestic Product (quarterly)
    "cpi": "CPIAUCSL",     # CPI All Urban Consumers
    "fed_rate": "FEDFUNDS", # Effective Federal Funds Rate
    "dgs2": "DGS2",        # 2-Year Treasury
    "dgs5": "DGS5",        # 5-Year Treasury
    "dgs10": "DGS10",      # 10-Year Treasury
    "dgs30": "DGS30",      # 30-Year Treasury
    "unemployment": "UNRATE",  # Unemployment Rate
}


def _fetch_fred_series(series_id: str, limit: int = 24, api_key: str = None) -> list:
    """Fetch a single FRED series. Returns list of {date, value} dicts."""
    if not api_key:
        api_key = os.getenv("FRED_API_KEY", "")

    if not api_key:
        return []

    resp = httpx.get(
        "https://api.stlouisfed.org/fred/series/observations",
        params={
            "series_id": series_id,
            "api_key": api_key,
            "file_type": "json",
            "sort_order": "desc",
            "limit": limit,
        },
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()
    observations = data.get("observations", [])
    result = []
    for obs in observations:
        try:
            value = float(obs["value"])
            result.append({"date": obs["date"], "value": value})
        except (ValueError, KeyError):
            continue
    return list(reversed(result))


def fetch_macro_data() -> dict:
    """
    Fetch macro dashboard data: GDP, CPI, Fed rate, yield curve, unemployment.
    Cached 1h. Returns empty structure on failure.
    """
    key = "macro:dashboard"
    cached = _cache_get(key, TTL_MACRO)
    if cached is not None:
        return cached

    api_key = os.getenv("FRED_API_KEY", "")

    def _fetch():
        gdp = _retry(lambda: _fetch_fred_series("GDP", 8, api_key), retries=2, backoff=(1, 3))
        cpi_raw = _retry(lambda: _fetch_fred_series("CPIAUCSL", 24, api_key), retries=2, backoff=(1, 3))
        fed_rate = _retry(lambda: _fetch_fred_series("FEDFUNDS", 24, api_key), retries=2, backoff=(1, 3))
        dgs2 = _retry(lambda: _fetch_fred_series("DGS2", 1, api_key), retries=2, backoff=(1, 3))
        dgs5 = _retry(lambda: _fetch_fred_series("DGS5", 1, api_key), retries=2, backoff=(1, 3))
        dgs10 = _retry(lambda: _fetch_fred_series("DGS10", 1, api_key), retries=2, backoff=(1, 3))
        dgs30 = _retry(lambda: _fetch_fred_series("DGS30", 1, api_key), retries=2, backoff=(1, 3))
        unemployment = _retry(lambda: _fetch_fred_series("UNRATE", 12, api_key), retries=2, backoff=(1, 3))

        # Compute YoY CPI
        cpi_enriched = []
        for i, item in enumerate(cpi_raw):
            entry = {"date": item["date"], "value": item["value"]}
            if i >= 12:
                prev = cpi_raw[i - 12]["value"]
                if prev:
                    entry["yoy_pct"] = round((item["value"] - prev) / prev * 100, 2)
            cpi_enriched.append(entry)

        yield_curve = {
            "DGS2": dgs2[-1]["value"] if dgs2 else None,
            "DGS5": dgs5[-1]["value"] if dgs5 else None,
            "DGS10": dgs10[-1]["value"] if dgs10 else None,
            "DGS30": dgs30[-1]["value"] if dgs30 else None,
        }

        return {
            "gdp": gdp,
            "cpi": cpi_enriched,
            "fed_rate": fed_rate,
            "yield_curve": yield_curve,
            "unemployment": unemployment,
            "calendar": _get_economic_calendar(api_key),
        }

    if not api_key:
        empty = {
            "gdp": [], "cpi": [], "fed_rate": [], "yield_curve": {},
            "unemployment": [], "calendar": [],
            "error": "未配置 FRED_API_KEY"
        }
        return empty

    try:
        result = _fetch()
        _cache_set(key, result)
        return result
    except Exception as e:
        logger.warning(f"fetch_macro_data() failed: {e}")
        stale = _cache_get(key, ttl=TTL_MACRO * 6)
        if stale:
            return stale
        return {"gdp": [], "cpi": [], "fed_rate": [], "yield_curve": {}, "unemployment": [], "calendar": [], "error": str(e)}


# ---------------------------------------------------------------------------
# Economic Calendar
# ---------------------------------------------------------------------------

# Fed meeting dates (2025-2026 FOMC schedule)
_FED_MEETINGS = [
    "2025-01-29", "2025-03-19", "2025-05-07", "2025-06-18",
    "2025-07-30", "2025-09-17", "2025-11-05", "2025-12-17",
    "2026-01-28", "2026-03-18", "2026-05-06", "2026-06-17",
    "2026-07-29", "2026-09-16", "2026-11-04", "2026-12-16",
]


def _get_fred_release_dates(release_id: str, api_key: str, limit: int = 3) -> list:
    """Fetch upcoming release dates for a FRED release."""
    if not api_key:
        return []
    try:
        resp = httpx.get(
            "https://api.stlouisfed.org/fred/release/dates",
            params={
                "release_id": release_id,
                "api_key": api_key,
                "file_type": "json",
                "sort_order": "desc",
                "limit": limit,
                "realtime_start": datetime.now().strftime("%Y-%m-%d"),
            },
            timeout=10,
        )
        resp.raise_for_status()
        return [d["date"] for d in resp.json().get("release_dates", [])]
    except Exception:
        return []


def _get_economic_calendar(api_key: str = None) -> list:
    """Build upcoming economic calendar from FRED + hardcoded Fed meeting dates."""
    today = datetime.now().date()
    events = []

    # Fed meetings
    for date_str in _FED_MEETINGS:
        date = datetime.strptime(date_str, "%Y-%m-%d").date()
        if date >= today:
            events.append({"date": date_str, "event": "FOMC 会议", "impact": "high"})

    # FRED releases (CPI=10, Jobs=50, GDP=17)
    if api_key:
        for release_id, name, impact in [("10", "CPI 发布", "high"), ("50", "非农就业", "high"), ("17", "GDP 发布", "medium")]:
            try:
                dates = _get_fred_release_dates(release_id, api_key)
                for d in dates:
                    events.append({"date": d, "event": name, "impact": impact})
            except Exception:
                pass

    # Sort by date, keep next 20 events
    events.sort(key=lambda x: x["date"])
    future = [e for e in events if e["date"] >= today.strftime("%Y-%m-%d")]
    return future[:20]


# ---------------------------------------------------------------------------
# Earnings calendar (from watchlist symbols)
# ---------------------------------------------------------------------------
def fetch_earnings_calendar(symbols: list) -> list:
    """
    Fetch upcoming earnings dates for a list of symbols.
    Returns sorted list of {symbol, date, eps_estimate}.
    """
    key = f"earnings:{','.join(sorted(symbols))}"
    cached = _cache_get(key, TTL_FUNDAMENTALS)
    if cached is not None:
        return cached

    results = []
    for symbol in symbols:
        try:
            ticker = yf.Ticker(symbol)
            ed = ticker.earnings_dates
            if ed is None or ed.empty:
                continue
            future = ed[ed.index > datetime.now()]
            if future.empty:
                continue
            next_date = future.index[0]
            eps_est = None
            if "EPS Estimate" in future.columns:
                eps_est = future["EPS Estimate"].iloc[0]
                if hasattr(eps_est, 'item'):
                    eps_est = float(eps_est) if not (eps_est != eps_est) else None
            results.append({
                "symbol": symbol.upper(),
                "date": next_date.strftime("%Y-%m-%d"),
                "eps_estimate": eps_est,
            })
        except Exception as e:
            logger.debug(f"fetch_earnings_calendar({symbol}): {e}")

    results.sort(key=lambda x: x["date"])
    _cache_set(key, results)
    return results


# ---------------------------------------------------------------------------
# Fama-French 3-Factor Data (30-day cache)
# ---------------------------------------------------------------------------
_FF_CACHE_PATH = None  # Will use in-memory dict entry


def fetch_fama_french_factors() -> dict:
    """
    Download and parse Ken French's daily 3-factor data.
    Returns dict with 'Mkt-RF', 'SMB', 'HML', 'RF' as pandas Series.
    Cached 30 days in memory. Falls back to None on error (use CAPM only).
    """
    key = "fama_french:daily"
    cached = _cache_get(key, TTL_FAMA_FRENCH)
    if cached is not None:
        return cached

    url = "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/F-F_Research_Data_Factors_daily_CSV.zip"

    try:
        import pandas as pd

        def _fetch():
            resp = httpx.get(url, timeout=30, follow_redirects=True)
            resp.raise_for_status()
            with zipfile.ZipFile(io.BytesIO(resp.content)) as z:
                csv_name = [n for n in z.namelist() if n.endswith(".CSV") or n.endswith(".csv")][0]
                with z.open(csv_name) as f:
                    # Skip header lines (find where numeric data starts)
                    content = f.read().decode("latin-1")

            lines = content.split("\n")
            data_start = 0
            for i, line in enumerate(lines):
                if line.strip() and line.strip()[0].isdigit():
                    data_start = i
                    break

            # Find footer (Annual Factors section)
            data_end = len(lines)
            for i in range(data_start, len(lines)):
                stripped = lines[i].strip()
                if stripped and not stripped[0].isdigit() and i > data_start + 10:
                    data_end = i
                    break

            data_lines = "\n".join(lines[data_start:data_end])
            df = pd.read_csv(io.StringIO(data_lines), header=None,
                             names=["Date", "Mkt-RF", "SMB", "HML", "RF"],
                             skipinitialspace=True)
            df = df.dropna()
            df["Date"] = pd.to_datetime(df["Date"].astype(str), format="%Y%m%d", errors="coerce")
            df = df.dropna(subset=["Date"])
            df = df.set_index("Date")
            df = df.astype(float) / 100.0  # Convert from % to decimal
            return df

        df = _retry(_fetch, retries=2, backoff=(2, 5))
        _cache_set(key, df)
        return df

    except Exception as e:
        logger.warning(f"fetch_fama_french_factors() failed: {e}. Will fall back to CAPM.")
        return None
