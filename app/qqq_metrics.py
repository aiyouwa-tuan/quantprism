"""QQQ (Nasdaq 100 ETF) 估值 & 技术指标 —— 通过 yfinance 拉取。

当前指标：价格 / RSI-14 / PE / PB / 股息率 / 1年涨幅
历史序列：价格 + RSI 月线 3/5/10/20Y + 当前价格分位
注：ETF 历史 PE/PB/ROE 时间序列 yfinance 无 — 需付费源，用价格分位代理
"""
import time
import yfinance as yf
import pandas as pd

_cache: dict = {}
_TTL = 900  # 15 min


def _cached(key, fn):
    entry = _cache.get(key)
    if entry and time.time() - entry["ts"] < _TTL:
        return entry["data"]
    data = fn()
    if not data.get("error"):
        _cache[key] = {"ts": time.time(), "data": data}
    return data


def _pe_estimate_series(close: pd.Series, current_eps_ttm: float, annual_growth: float = 0.14) -> pd.Series:
    """近似历史 PE 时间序列。

    方法：已知当前 trailing EPS，假设 EPS 以年化 `annual_growth`（默认14%，
    NDX 过去20年trailing EPS大致水平）反向复合衰减到每个历史月份，
    然后用各月收盘价除以当月估算 EPS 得到估算 PE。

    注意：这是估算，非真实历史 PE（ETF 历史 PE 需付费数据源）。
    曲线形状合理反映"贵/便宜"变化，绝对值仅供参考。
    """
    if current_eps_ttm is None or current_eps_ttm <= 0:
        return pd.Series([None] * len(close), index=close.index)
    now = close.index[-1]
    # 每个点距 now 的年数（负值表示过去）
    deltas = [(idx - now).days / 365.25 for idx in close.index]
    # 历史 EPS = current / (1+g)^(-years_back)
    hist_eps = [current_eps_ttm / ((1 + annual_growth) ** (-d)) for d in deltas]
    return pd.Series([float(p) / float(e) if e and e > 0 else None
                      for p, e in zip(close.values, hist_eps)], index=close.index)


def _rsi_series(close: pd.Series, period: int = 14) -> pd.Series:
    """Wilder's RSI — 返回整个时间序列。"""
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, 1e-10)
    return 100 - (100 / (1 + rs))


def _percentile(series: pd.Series, value: float) -> float:
    if len(series) == 0:
        return 50.0
    return float((series <= value).mean() * 100)


def fetch_qqq() -> dict:
    def _fetch():
        try:
            tk = yf.Ticker("QQQ")
            info = tk.info or {}

            # 日线 6M 用于 RSI 当前值（日 RSI 更灵敏）
            daily = tk.history(period="6mo", interval="1d")
            rsi_current = None
            if not daily.empty:
                rsi_current = float(_rsi_series(daily["Close"]).iloc[-1])

            # 月线 max 用于 20 年历史
            monthly = tk.history(period="max", interval="1mo")
            if monthly.empty:
                return {"error": "no price history"}

            # 计算月线 RSI（滚动 14 个月窗口）
            monthly_rsi = _rsi_series(monthly["Close"])

            # 估算历史 PE（基于当前 PE/价格推当前 EPS，再按 14% 年化衰减）
            pe_now = info.get("trailingPE")
            current_eps = None
            if pe_now and float(pe_now) > 0:
                current_eps = float(monthly["Close"].iloc[-1]) / float(pe_now)
            pe_growth_assumption = 0.14
            monthly_pe_est = _pe_estimate_series(monthly["Close"], current_eps, pe_growth_assumption)

            # 按周期切片 + 结构化数据
            def _series(df, rsi_df, pe_df):
                out = []
                for idx, row in df.iterrows():
                    if pd.isna(row["Close"]):
                        continue
                    rsi_val = rsi_df.loc[idx] if idx in rsi_df.index else None
                    pe_val = pe_df.loc[idx] if idx in pe_df.index else None
                    out.append({
                        "date": int(idx.timestamp() * 1000),
                        "close": round(float(row["Close"]), 2),
                        "rsi": round(float(rsi_val), 1) if rsi_val is not None and not pd.isna(rsi_val) else None,
                        "pe_est": round(float(pe_val), 1) if pe_val is not None and not pd.isna(pe_val) else None,
                    })
                return out

            now = monthly.index[-1]
            slices = {
                "3y": monthly[monthly.index >= now - pd.DateOffset(years=3)],
                "5y": monthly[monthly.index >= now - pd.DateOffset(years=5)],
                "10y": monthly[monthly.index >= now - pd.DateOffset(years=10)],
                "20y": monthly[monthly.index >= now - pd.DateOffset(years=20)],
            }
            history = {k: _series(v, monthly_rsi, monthly_pe_est) for k, v in slices.items()}

            current_price = float(monthly["Close"].iloc[-1])

            # 价格分位
            pct = {k: round(_percentile(v["Close"], current_price), 1) for k, v in slices.items()}

            # 1年涨幅
            one_year_ago = monthly[monthly.index <= now - pd.DateOffset(years=1)]
            yoy_return = None
            if not one_year_ago.empty:
                prev = float(one_year_ago["Close"].iloc[-1])
                yoy_return = round((current_price / prev - 1) * 100, 2)

            pe = info.get("trailingPE")
            pb = info.get("priceToBook")
            dividend_yield = info.get("yield")
            if dividend_yield is None:
                dy = info.get("dividendYield")
                if dy is not None:
                    dividend_yield = dy / 100 if dy > 1 else dy

            return {
                "error": None,
                "current": {
                    "price": round(current_price, 2),
                    "rsi14": round(rsi_current, 1) if rsi_current is not None else None,
                    "pe": round(float(pe), 2) if pe else None,
                    "pb": round(float(pb), 2) if pb else None,
                    "dividend_yield_pct": round(float(dividend_yield) * 100, 2) if dividend_yield else None,
                    "yoy_return_pct": yoy_return,
                },
                "percentile": pct,
                "history": history,
            }
        except Exception as e:
            return {"error": str(e)}

    return _cached("qqq", _fetch)
