"""
金渐成数据层

优先级：
  1. VPS PostgreSQL (ssh + psql，本机/VPS 均可用)
  2. yfinance（兜底）
"""
from __future__ import annotations
import time
import subprocess
import json
import numpy as np
from market_data import fetch_stock_history

TARGET_SYMBOLS = ["NVDA", "META", "MSFT", "GOOGL", "AMZN", "TSLA", "AAPL", "TSM", "QQQ"]

VPS_HOST   = "82.180.131.159"
VPS_KEY    = "/Users/marobin/.ssh/id_ed25519"
VPS_PG_URL = "postgresql://alphalens_market:mkt_Al9xK2pQ7vNw3eR@127.0.0.1:5432/alphalens_market"

_summary_cache: dict = {}
_SUMMARY_TTL = 300


# ---------------------------------------------------------------------------
# VPS 查询工具
# ---------------------------------------------------------------------------

def _direct_query(sql: str, timeout: int = 20) -> list[dict] | None:
    """直接连本机 psql（VPS 上运行时使用，无需 SSH）。"""
    import csv, io
    try:
        result = subprocess.run(
            ["psql", VPS_PG_URL, "--no-align", "--csv"],
            input=sql,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode != 0 or not result.stdout.strip():
            return None
        reader = csv.DictReader(io.StringIO(result.stdout))
        rows = [dict(r) for r in reader]
        return rows if rows else None
    except Exception:
        return None


def _ssh_query(sql: str, timeout: int = 20) -> list[dict] | None:
    """先试直连 psql（VPS 环境），失败再走 SSH（本机开发环境）。"""
    # 直连成功（在 VPS 上运行时），直接返回
    rows = _direct_query(sql, timeout)
    if rows is not None:
        return rows

    # 回退到 SSH（本机开发）
    ssh_cmd = [
        "ssh", "-i", VPS_KEY,
        "-o", "BatchMode=yes",
        "-o", "StrictHostKeyChecking=no",
        "-o", f"ConnectTimeout={timeout}",
        f"root@{VPS_HOST}",
        f"psql '{VPS_PG_URL}' --no-align --csv",
    ]
    try:
        result = subprocess.run(
            ssh_cmd,
            input=sql,
            capture_output=True,
            text=True,
            timeout=timeout + 5,
        )
        if result.returncode != 0 or not result.stdout.strip():
            return None
        import csv, io
        reader = csv.DictReader(io.StringIO(result.stdout))
        rows = [dict(r) for r in reader]
        return rows if rows else None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# VPS → summary
# ---------------------------------------------------------------------------

_SUMMARY_SQL = """
WITH daily AS (
  SELECT symbol, DATE(ts) AS date, close, high, low, open, volume
  FROM stock_candles
  WHERE symbol IN ('NVDA.US','META.US','MSFT.US','GOOGL.US',
                   'AMZN.US','TSLA.US','AAPL.US','TSM.US','QQQ.US')
    AND period = 'day'
),
ma_calc AS (
  SELECT *,
    AVG(close) OVER (PARTITION BY symbol ORDER BY date
                     ROWS BETWEEN 199 PRECEDING AND CURRENT ROW) AS ma200,
    AVG(close) OVER (PARTITION BY symbol ORDER BY date
                     ROWS BETWEEN 49  PRECEDING AND CURRENT ROW) AS ma50,
    ROW_NUMBER() OVER (PARTITION BY symbol ORDER BY date DESC)    AS rn
  FROM daily
),
week52 AS (
  SELECT symbol,
    MAX(close) AS high_52w,
    MIN(close) AS low_52w
  FROM daily
  WHERE date >= CURRENT_DATE - INTERVAL '365 days'
  GROUP BY symbol
)
SELECT
  m.symbol,
  m.date::text                                                    AS latest_date,
  ROUND(m.close::numeric, 2)                                      AS close,
  ROUND(m.open::numeric,  2)                                      AS open,
  ROUND(m.high::numeric,  2)                                      AS day_high,
  ROUND(m.low::numeric,   2)                                      AS day_low,
  m.volume,
  ROUND(m.ma50::numeric,  2)                                      AS ma50,
  ROUND(m.ma200::numeric, 2)                                      AS ma200,
  ROUND(((m.close - m.ma200) / m.ma200 * 100)::numeric, 1)       AS pct_vs_ma200,
  ROUND(((m.close - m.ma50)  / m.ma50  * 100)::numeric, 1)       AS pct_vs_ma50,
  ROUND(w.high_52w::numeric, 2)                                   AS high_52w,
  ROUND(w.low_52w::numeric,  2)                                   AS low_52w,
  ROUND(((m.close - w.low_52w)
       / NULLIF(w.high_52w - w.low_52w, 0) * 100)::numeric, 1)  AS pct_in_52w_range
FROM ma_calc m
JOIN week52 w ON m.symbol = w.symbol
WHERE m.rn = 1
ORDER BY m.symbol;
"""

def _fetch_summary_vps() -> list[dict] | None:
    rows = _ssh_query(_SUMMARY_SQL)
    if not rows:
        return None
    results = []
    for r in rows:
        sym = r["symbol"].replace(".US", "")
        try:
            results.append({
                "symbol":           sym,
                "latest_date":      r.get("latest_date", ""),
                "close":            float(r["close"]),
                "open":             float(r["open"]),
                "day_high":         float(r["day_high"]),
                "day_low":          float(r["day_low"]),
                "volume":           int(r["volume"]),
                "ma50":             float(r["ma50"]),
                "ma200":            float(r["ma200"]),
                "pct_vs_ma200":     float(r["pct_vs_ma200"]),
                "pct_vs_ma50":      float(r["pct_vs_ma50"]),
                "high_52w":         float(r["high_52w"]),
                "low_52w":          float(r["low_52w"]),
                "pct_in_52w_range": float(r["pct_in_52w_range"]),
                "source":           "vps",
            })
        except (KeyError, ValueError):
            continue
    return results if results else None


# ---------------------------------------------------------------------------
# yfinance → summary（兜底）
# ---------------------------------------------------------------------------

def _pct(a, b) -> float:
    if not b or b == 0:
        return 0.0
    return round((a - b) / b * 100, 1)

def _pct_in_range(close, low, high) -> float:
    diff = high - low
    if diff == 0:
        return 50.0
    return round((close - low) / diff * 100, 1)

def _fetch_summary_yfinance() -> list[dict]:
    results = []
    for sym in TARGET_SYMBOLS:
        try:
            df = fetch_stock_history(sym, period="1y")
            if df is None or len(df) < 50:
                continue
            df = df.sort_index()
            closes = df["close"].values
            ma50  = float(np.mean(closes[-50:]))
            ma200 = float(np.mean(closes[-min(200, len(closes)):]))
            close = float(closes[-1])
            high_52w = float(closes.max())
            low_52w  = float(closes.min())
            row = df.iloc[-1]
            results.append({
                "symbol":           sym,
                "latest_date":      df.index[-1].strftime("%Y-%m-%d"),
                "close":            round(close, 2),
                "open":             round(float(row.get("open", close)), 2),
                "day_high":         round(float(row.get("high", close)), 2),
                "day_low":          round(float(row.get("low", close)), 2),
                "volume":           int(row.get("volume", 0)),
                "ma50":             round(ma50, 2),
                "ma200":            round(ma200, 2),
                "pct_vs_ma200":     _pct(close, ma200),
                "pct_vs_ma50":      _pct(close, ma50),
                "high_52w":         round(high_52w, 2),
                "low_52w":          round(low_52w, 2),
                "pct_in_52w_range": _pct_in_range(close, low_52w, high_52w),
                "source":           "yfinance",
            })
        except Exception:
            continue
    return results


# ---------------------------------------------------------------------------
# 公开接口
# ---------------------------------------------------------------------------

def fetch_summary() -> list[dict]:
    now = time.time()
    if "data" in _summary_cache and now - _summary_cache.get("ts", 0) < _SUMMARY_TTL:
        return _summary_cache["data"]

    data = _fetch_summary_vps()
    if not data:
        data = _fetch_summary_yfinance()

    _summary_cache["data"] = data
    _summary_cache["ts"] = now
    return data


# ---------------------------------------------------------------------------
# VPS → candles（含 streak 计算）
# ---------------------------------------------------------------------------

def _fetch_candles_vps(symbol: str, limit: int = 60) -> list[dict] | None:
    sym_us = symbol + ".US"
    # 取更多行以便计算 MA200 和 streak
    sql = f"""
    SELECT DATE(ts)::text AS date, open, high, low, close, volume
    FROM stock_candles
    WHERE symbol = '{sym_us}' AND period = 'day'
    ORDER BY ts DESC LIMIT 260;
    """
    rows = _ssh_query(sql)
    if not rows:
        return None
    rows = list(reversed(rows))  # 时间正序
    closes = [float(r["close"]) for r in rows]
    candles = []
    for i, r in enumerate(rows):
        ma50  = round(float(np.mean(closes[max(0, i-49):i+1])),  2) if i >= 0 else None
        ma200 = round(float(np.mean(closes[max(0, i-199):i+1])), 2) if i >= 0 else None
        candles.append({
            "date":   r["date"],
            "open":   round(float(r["open"]),   2),
            "high":   round(float(r["high"]),   2),
            "low":    round(float(r["low"]),    2),
            "close":  round(float(r["close"]),  2),
            "volume": int(r["volume"]),
            "ma50":   ma50,
            "ma200":  ma200,
            "source": "vps",
        })
    return candles[-limit:]


def _fetch_candles_yfinance(symbol: str, limit: int = 60) -> list[dict]:
    try:
        df = fetch_stock_history(symbol, period="2y")
        if df is None or df.empty:
            return []
        df = df.sort_index().tail(max(limit, 200))
        closes = df["close"].values
        candles = []
        for i, (idx, row) in enumerate(df.iterrows()):
            ma50  = round(float(np.mean(closes[max(0, i-49):i+1])),  2)
            ma200 = round(float(np.mean(closes[max(0, i-199):i+1])), 2)
            candles.append({
                "date":   idx.strftime("%Y-%m-%d"),
                "open":   round(float(row["open"]),   2),
                "high":   round(float(row["high"]),   2),
                "low":    round(float(row["low"]),    2),
                "close":  round(float(row["close"]),  2),
                "volume": int(row["volume"]),
                "ma50":   ma50,
                "ma200":  ma200,
                "source": "yfinance",
            })
        return candles[-limit:]
    except Exception:
        return []


def fetch_candles(symbol: str, limit: int = 60) -> list[dict]:
    sym = symbol.replace(".US", "").upper()
    data = _fetch_candles_vps(sym, limit)
    if not data:
        data = _fetch_candles_yfinance(sym, limit)
    return data or []
