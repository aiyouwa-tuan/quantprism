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
CACHE_TTL_SECONDS = 3600  # 1 hour


def _cache_path(query_id: str) -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return CACHE_DIR / f"flex_{query_id}.xml"


def _read_cache(query_id: str) -> Optional[str]:
    p = _cache_path(query_id)
    if not p.exists():
        return None
    if time.time() - p.stat().st_mtime > CACHE_TTL_SECONDS:
        return None
    try:
        return p.read_text()
    except Exception:
        return None


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
            # Retry up to 12 times with backoff (2s .. 24s)
            for attempt in range(12):
                time.sleep(2 + attempt)
                r2 = client.get(url, params={"q": ref_code, "t": token, "v": "3"})
                if r2.status_code != 200:
                    continue
                # If still generating, response is <FlexStatementResponse><Status>Warn</Status>...
                try:
                    root2 = ET.fromstring(r2.text)
                    status2 = root2.findtext("Status")
                    if status2 == "Warn":
                        continue  # still generating
                except ET.ParseError:
                    pass
                # Got the report
                _write_cache(query_id, r2.text)
                return r2.text

            log.error("flex GetStatement timed out after retries")
            return None
    except Exception as exc:
        log.exception("flex fetch exception: %s", exc)
        return None


def parse_cashflow(xml_text: str) -> dict:
    """
    Parse Flex XML to extract aggregate cashflow metrics.

    Returns:
      {
        "netDeposits": float,       # deposits - withdrawals
        "totalDividends": float,    # dividends + payments in lieu
        "totalInterest": float,     # interest credited
        "totalFees": float,         # commissions + fees (positive)
        "totalCommission": float,
        "tradeCount": int,
      }
    """
    result = {
        "netDeposits": 0.0,
        "totalDividends": 0.0,
        "totalInterest": 0.0,
        "totalFees": 0.0,
        "totalCommission": 0.0,
        "tradeCount": 0,
    }
    if not xml_text:
        return result

    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        log.error("flex XML parse error: %s", exc)
        return result

    # Cash transactions: <CashTransaction type="..." amount="..." />
    for tx in root.iter("CashTransaction"):
        try:
            amount = float(tx.get("amount") or 0)
        except ValueError:
            amount = 0.0
        tx_type = (tx.get("type") or "").strip()
        # IBKR types: "Deposits/Withdrawals", "Dividends", "Broker Interest Received",
        # "Broker Interest Paid", "Payment In Lieu Of Dividends", "Withholding Tax",
        # "Commission Adjustments", "Other Fees"
        if tx_type == "Deposits/Withdrawals":
            result["netDeposits"] += amount
        elif tx_type in ("Dividends", "Payment In Lieu Of Dividends"):
            result["totalDividends"] += amount
        elif tx_type in ("Broker Interest Received", "Broker Interest Paid"):
            result["totalInterest"] += amount
        elif tx_type in ("Withholding Tax", "Other Fees", "Commission Adjustments"):
            result["totalFees"] += amount

    # Trade commissions
    for tr in root.iter("Trade"):
        result["tradeCount"] += 1
        try:
            # IBKR trades store commission as negative (cost to user)
            comm = float(tr.get("ibCommission") or 0)
            result["totalCommission"] += abs(comm)
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
        symbol = tr.get("symbol") or tr.get("underlyingSymbol") or ""
        sec_type = tr.get("assetCategory") or "STK"
        # IBKR sides: "BUY" / "SELL"; quantity sign indicates direction
        side = "BUY" if qty > 0 else "SELL"
        # Build positionKey: for options, include strike+expiry+right
        if sec_type == "OPT":
            strike = tr.get("strike") or ""
            expiry = tr.get("expiry") or ""
            right = tr.get("putCall") or ""
            pos_key = f"{symbol} {expiry}{right}{strike}".strip()
        else:
            pos_key = symbol
        trades.append({
            "symbol": symbol,
            "positionKey": pos_key,
            "secType": sec_type,
            "side": side,
            "quantity": abs(qty),
            "price": price,
            "multiplier": int(mult),
            "commission": comm,
            "tradeTime": tr.get("tradeDate") or tr.get("dateTime") or "",
        })
    return trades


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
