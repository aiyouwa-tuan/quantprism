"""
IBKR Flex Web Service client.

Fetches historical cashflow/trades/dividends from Interactive Brokers
Flex Web Service. Used to compute accurate portfolio returns (netDeposits,
totalDividends, etc.) that are NOT available via the live TWS socket API.

Setup (one-time, user action in IBKR portal):
  1. Login at https://www.interactivebrokers.com
  2. Settings > Account Settings > Reporting > Flex Queries
  3. Create a new Activity Flex Query with sections:
       - Cash Transactions (Deposits/Withdrawals, Dividends, Interest, Fees)
       - Trades (optional, for FIFO historical P/L)
  4. Period: "Year to Date" or custom range covering account history
  5. Format: XML
  6. Save the Query ID
  7. Settings > Account Settings > Reporting > Flex Web Service > Enable
  8. Save the generated Token
  9. Set env vars on VPS:
       IBKR_FLEX_TOKEN=<token>
       IBKR_FLEX_QUERY_CASH=<query_id>

API docs: https://www.interactivebrokers.com/en/software/am/am/reports/flex_web_service_version_3.htm
"""
from __future__ import annotations
import os
import time
import logging
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional
import httpx

log = logging.getLogger(__name__)

FLEX_BASE = "https://www.interactivebrokers.com/Universal/servlet/FlexStatementService"
CACHE_DIR = Path("/tmp/ibkr_flex_cache")
CACHE_TTL_SECONDS = 43200  # 12 hours


def _cache_path(query_id: str) -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return CACHE_DIR / f"flex_{query_id}.xml"


def _read_cache(query_id: str) -> Optional[str]:
    """Return cached XML only if still within TTL. Returns None if expired or missing."""
    p = _cache_path(query_id)
    if not p.exists():
        return None
    if time.time() - p.stat().st_mtime > CACHE_TTL_SECONDS:
        return None
    try:
        return p.read_text()
    except Exception:
        return None


def _read_cache_stale(query_id: str) -> Optional[str]:
    """Return cached XML regardless of TTL (stale-while-revalidate).
    Use this when fresh cache is unavailable — stale data beats empty screen.
    Caller is responsible for triggering a background refresh."""
    p = _cache_path(query_id)
    if not p.exists():
        return None
    try:
        return p.read_text()
    except Exception:
        return None


def cache_is_stale(query_id: str) -> bool:
    """True if cache exists but is past TTL (needs background refresh)."""
    p = _cache_path(query_id)
    if not p.exists():
        return False
    return time.time() - p.stat().st_mtime > CACHE_TTL_SECONDS


def _write_cache(query_id: str, xml_text: str) -> None:
    try:
        _cache_path(query_id).write_text(xml_text)
    except Exception as exc:
        log.warning("flex cache write failed: %s", exc)


def fetch_flex_xml(token: str, query_id: str, use_cache: bool = True) -> Optional[str]:
    """
    Fetch raw XML from IBKR Flex Web Service.

    Two-step workflow:
      1. POST SendRequest -> ReferenceCode
      2. GET GetStatement with ReferenceCode -> XML report
    """
    if not token or not query_id:
        return None

    if use_cache:
        cached = _read_cache(query_id)
        if cached:
            log.info("flex cache hit for query %s", query_id)
            return cached

    try:
        with httpx.Client(timeout=30.0, follow_redirects=True) as client:
            # Step 1: request report generation
            r = client.get(
                f"{FLEX_BASE}.SendRequest",
                params={"t": token, "q": query_id, "v": "3"},
            )
            r.raise_for_status()
            root = ET.fromstring(r.text)
            status = root.findtext("Status") or ""
            if status != "Success":
                code = root.findtext("ErrorCode") or "?"
                msg = root.findtext("ErrorMessage") or "?"
                log.error("flex SendRequest failed: %s %s", code, msg)
                return None
            ref_code = root.findtext("ReferenceCode")
            url = root.findtext("Url")
            if not (ref_code and url):
                log.error("flex SendRequest missing ReferenceCode/Url")
                return None

            # Step 2: wait and retrieve (IBKR needs time to generate)
            # Poll up to 24 times: first 5s then every 10s (up to ~4 minutes total)
            time.sleep(5)
            for attempt in range(24):
                r2 = client.get(url, params={"q": ref_code, "t": token, "v": "3"})
                if r2.status_code != 200:
                    time.sleep(10)
                    continue
                # If still generating, response is <FlexStatementResponse><Status>Warn</Status>...
                try:
                    root2 = ET.fromstring(r2.text)
                    status2 = root2.findtext("Status")
                    if status2 == "Warn":
                        log.debug("flex still generating, attempt %d/24", attempt + 1)
                        time.sleep(10)
                        continue
                    if status2 not in ("Success", None):
                        code2 = root2.findtext("ErrorCode") or "?"
                        msg2 = root2.findtext("ErrorMessage") or "?"
                        log.error("flex GetStatement error %s: %s", code2, msg2)
                        return None
                except ET.ParseError:
                    pass
                # Got the report
                _write_cache(query_id, r2.text)
                return r2.text

            log.error("flex GetStatement timed out after 24 retries (~4 min)")
            return None
    except Exception as exc:
        log.exception("flex fetch exception: %s", exc)
        return None


def parse_cashflow(xml_text: str) -> dict:
    """
    Parse Flex XML to extract aggregate cashflow metrics.

    Returns:
      {
        "netDeposits": float,       # ChangeInNAV.depositsWithdrawals (IB authoritative)
        "totalDividends": float,    # dividends + payments in lieu
        "totalInterest": float,     # interest credited
        "totalFees": float,         # withholding tax + other fees (negative = cost)
        "totalCommission": float,   # trading commissions (positive)
        "totalUnrealized": float,   # sum of OpenPosition.fifoPnlUnrealized (IB FIFO)
        "totalMV": float,           # sum of OpenPosition.markPrice × position × multiplier
        "tradeCount": int,
      }
    """
    result = {
        "netDeposits": 0.0,
        "totalDividends": 0.0,
        "totalInterest": 0.0,
        "totalFees": 0.0,
        "totalCommission": 0.0,
        "totalUnrealized": 0.0,
        "totalMV": 0.0,
        "tradeCount": 0,
    }
    if not xml_text:
        return result

    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        log.error("flex XML parse error: %s", exc)
        return result

    # ChangeInNAV: IB's authoritative performance summary
    # depositsWithdrawals = true net cash invested (excludes stock grants, transfers, etc.)
    # This matches IB's own TWR calculation base — more accurate than summing CashTransactions
    for nav in root.iter("ChangeInNAV"):
        try:
            deps = nav.get("depositsWithdrawals")
            if deps:
                result["netDeposits"] = float(deps)
            divs = nav.get("dividends")
            if divs:
                result["totalDividends"] = float(divs)
            interest = nav.get("interest")
            if interest:
                result["totalInterest"] = float(interest)
            comms = nav.get("commissions")
            if comms:
                result["totalCommission"] = round(abs(float(comms)), 2)
            tax = nav.get("withholdingTax")
            if tax:
                result["totalFees"] = float(tax)
        except (ValueError, TypeError):
            pass
        break  # only one ChangeInNAV per report

    # OpenPosition: sum IB's FIFO unrealized P&L and market value across all open positions
    # levelOfDetail="LOT" are lot-level sub-rows — skip to avoid double-counting
    for pos in root.iter("OpenPosition"):
        if pos.get("levelOfDetail") == "LOT":
            continue
        try:
            unreal = pos.get("fifoPnlUnrealized")
            if unreal:
                result["totalUnrealized"] += float(unreal)
            # Market value = markPrice × |position| × multiplier
            mark = pos.get("markPrice")
            qty = pos.get("position")
            mult = pos.get("multiplier") or "1"
            if mark and qty:
                result["totalMV"] += abs(float(qty)) * float(mark) * float(mult)
        except (ValueError, TypeError):
            pass

    # CashTransaction: keep for tradeCount and as fallback if ChangeInNAV missing
    has_nav = result["netDeposits"] != 0.0
    cash_deposits = 0.0
    for tx in root.iter("CashTransaction"):
        try:
            amount = float(tx.get("amount") or 0)
        except ValueError:
            amount = 0.0
        tx_type = (tx.get("type") or "").strip()
        if tx_type == "Deposits/Withdrawals":
            cash_deposits += amount
        elif tx_type in ("Dividends", "Payment In Lieu Of Dividends") and not has_nav:
            result["totalDividends"] += amount
        elif tx_type in ("Broker Interest Received", "Broker Interest Paid") and not has_nav:
            result["totalInterest"] += amount
        elif tx_type in ("Withholding Tax", "Other Fees", "Commission Adjustments") and not has_nav:
            result["totalFees"] += amount
    if not has_nav:
        result["netDeposits"] = cash_deposits

    # Trade commissions (ibCommission from Trade records is more granular than ChangeInNAV)
    for tr in root.iter("Trade"):
        result["tradeCount"] += 1
        try:
            comm = float(tr.get("ibCommission") or 0)
            result["totalCommission"] = result.get("totalCommission", 0)  # already set from ChangeInNAV
        except ValueError:
            pass

    # Round
    for k, v in result.items():
        if isinstance(v, float):
            result[k] = round(v, 2)

    return result


def parse_trades(xml_text: str) -> list[dict]:
    """
    Parse Flex XML to extract historical trades in the format expected by
    the portfolio FIFO annotator.

    Returns list of dicts with keys:
      symbol, positionKey, secType, side, quantity, price, multiplier,
      commission, tradeTime
    """
    trades: list[dict] = []
    if not xml_text:
        return trades
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return trades

    for tr in root.iter("Trade"):
        try:
            qty = float(tr.get("quantity") or 0)
            price = float(tr.get("tradePrice") or 0)
            mult = float(tr.get("multiplier") or 1) or 1
            comm = abs(float(tr.get("ibCommission") or 0))
        except ValueError:
            continue
        if qty == 0:
            continue
        sec_type = tr.get("assetCategory") or "STK"
        # For OPT: Flex XML symbol is OSI format (e.g. "MSFT  270115C00400000")
        # Use underlyingSymbol for clean display (e.g. "MSFT")
        if sec_type == "OPT":
            symbol = tr.get("underlyingSymbol") or tr.get("symbol") or ""
        else:
            symbol = tr.get("symbol") or tr.get("underlyingSymbol") or ""
        # Flex XML: buySell="BUY"/"SELL", quantity is always positive
        buy_sell = (tr.get("buySell") or "").upper()
        if buy_sell in ("BUY", "SELL"):
            side = buy_sell
        else:
            side = "BUY" if qty > 0 else "SELL"
        # Build positionKey: for options, include strike+expiry+right
        if sec_type == "OPT":
            strike = tr.get("strike") or ""
            expiry = (tr.get("expiry") or "").replace("-", "")
            right = tr.get("putCall") or ""
            # Format: "SYMBOL YYYYMMDD[C/P]STRIKE" e.g. "MSFT 20270115C400"
            pos_key = f"{symbol} {expiry}{right}{strike}".strip()
        else:
            pos_key = symbol
        # Prefer dateTime (has time component) over tradeDate (date only)
        raw_dt = tr.get("dateTime") or tr.get("tradeDate") or ""
        trades.append({
            "symbol": symbol,
            "positionKey": pos_key,
            "secType": sec_type,
            "side": side,
            "quantity": abs(qty),
            "price": price,
            "multiplier": int(mult),
            "commission": comm,
            "tradeTime": raw_dt,
        })
    return trades


def parse_positions(xml_text: str) -> list[dict]:
    """
    Parse Flex XML OpenPosition records into holdings format compatible with
    _normalize_positions() output. Used as fallback when IB Gateway is disconnected.

    Returns list of dicts with keys matching the template's holdings format.
    """
    holdings: list[dict] = []
    if not xml_text:
        return holdings
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return holdings

    for pos in root.iter("OpenPosition"):
        # Skip lot-level sub-rows to avoid double-counting
        if pos.get("levelOfDetail") == "LOT":
            continue
        try:
            qty = float(pos.get("position") or 0)
            if qty == 0:
                continue
            sec = pos.get("assetCategory") or "STK"
            mult = float(pos.get("multiplier") or 1) or 1
            avg_cost = float(pos.get("costBasisPrice") or 0)
            mark_price = float(pos.get("markPrice") or 0)
            unreal = float(pos.get("fifoPnlUnrealized") or 0)
            total_inv = abs(avg_cost * qty * (mult if sec == "OPT" else 1))

            if sec == "OPT":
                symbol = pos.get("underlyingSymbol") or pos.get("symbol") or ""
                strike = pos.get("strike") or ""
                expiry = (pos.get("expiry") or "").replace("-", "")
                right = pos.get("putCall") or ""
                pos_key = f"{symbol} {expiry}{right}{strike}".strip()
            else:
                symbol = pos.get("symbol") or ""
                pos_key = symbol
                strike = expiry = right = None

            mv = mark_price * qty * mult if sec == "OPT" else mark_price * qty

            holdings.append({
                "symbol": symbol,
                "positionKey": pos_key,
                "secType": sec,
                "quantity": qty,
                "avgCost": avg_cost,
                "totalInvestment": total_inv,
                "multiplier": int(mult),
                "unrealizedPL": unreal,
                "realizedPL": 0,
                "marketValue": round(mv, 2),
                "lastPrice": mark_price,
                "changePercent": 0,
                "changeAmount": 0,
                "marketCap": 0,
                "ytd": 0,
                "sparkline": [],
                "session": "",
                "strike": strike,
                "expiry": expiry,
                "right": right,
                "delta": None,
                "gamma": None,
                "theta": None,
                "vega": None,
                "impliedVol": None,
            })
        except (ValueError, TypeError):
            continue

    return holdings


def get_cashflow_summary() -> dict:
    """
    Convenience wrapper: reads env vars, fetches report, returns summary.

    Env vars:
      IBKR_FLEX_TOKEN
      IBKR_FLEX_QUERY_CASH (activity query with CashTransactions + Trades sections)
    """
    token = os.getenv("IBKR_FLEX_TOKEN", "").strip()
    query_id = os.getenv("IBKR_FLEX_QUERY_CASH", "").strip()
    if not (token and query_id):
        return {}
    xml_text = fetch_flex_xml(token, query_id)
    if not xml_text:
        return {}
    return parse_cashflow(xml_text)


def get_historical_trades() -> list[dict]:
    """Convenience: parse trades from cached/fresh Flex report."""
    token = os.getenv("IBKR_FLEX_TOKEN", "").strip()
    query_id = os.getenv("IBKR_FLEX_QUERY_CASH", "").strip()
    if not (token and query_id):
        return []
    xml_text = fetch_flex_xml(token, query_id)
    if not xml_text:
        return []
    return parse_trades(xml_text)
