"""
Goal-Driven Trading OS — Trading Memory System
BM25 retrieval of similar past analyses + reflection on closed trades.
"""
import json
import logging
from datetime import datetime, date
from typing import Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Store analysis result
# ---------------------------------------------------------------------------

def store_analysis(symbol: str, analysis_result: dict, diagnosis: dict) -> int:
    """
    Persist a multi-agent analysis result to analysis_memory table.
    Returns the new record ID.

    Args:
        symbol: Stock symbol
        analysis_result: Output of multi_agent.run_analysis()
        diagnosis: StockDiagnosis as dict (for scenario text)
    """
    from models import SessionLocal, AnalysisMemory

    scenario_text = _build_scenario_text(symbol, diagnosis, analysis_result)

    db = SessionLocal()
    try:
        record = AnalysisMemory(
            symbol=symbol.upper(),
            analysis_date=date.today().strftime("%Y-%m-%d"),
            scenario_text=scenario_text,
            analysis_json=json.dumps(analysis_result, ensure_ascii=False),
            created_at=datetime.utcnow(),
        )
        db.add(record)
        db.commit()
        db.refresh(record)
        return record.id
    except Exception as e:
        db.rollback()
        logger.warning(f"store_analysis({symbol}) failed: {e}")
        return -1
    finally:
        db.close()


def _build_scenario_text(symbol: str, diagnosis: dict, analysis_result: dict) -> str:
    """Build human-readable scenario string for BM25 indexing."""
    trend = diagnosis.get("trend", "unknown")
    rsi = diagnosis.get("rsi", 0)
    iv_rank = diagnosis.get("iv_rank", 0)
    score = diagnosis.get("score", 0)
    bb = diagnosis.get("bb_position", "unknown")
    safety = diagnosis.get("safety_margin", 0)

    verdict_snippet = ""
    if analysis_result.get("verdict"):
        verdict_snippet = analysis_result["verdict"][:100]

    return (
        f"{symbol} trend:{trend} rsi:{rsi:.0f} iv_rank:{iv_rank:.0f} "
        f"score:{score} bb:{bb} safety_margin:{safety*100:.0f}pct "
        f"verdict:{verdict_snippet}"
    )


# ---------------------------------------------------------------------------
# BM25 retrieval
# ---------------------------------------------------------------------------

def retrieve_similar(symbol: str, diagnosis: dict, limit: int = 3) -> list:
    """
    Find similar past analyses using BM25 text similarity.
    Falls back to recent analyses if rank_bm25 not installed.

    Args:
        symbol: Stock symbol (included in query for same-symbol boost)
        diagnosis: Current StockDiagnosis as dict
        limit: Max number of results

    Returns:
        List of dicts: {date, symbol, scenario, outcome, lesson}
    """
    from models import SessionLocal, AnalysisMemory

    db = SessionLocal()
    try:
        rows = db.query(AnalysisMemory).filter(
            AnalysisMemory.outcome_json.isnot(None)  # only completed trades
        ).order_by(AnalysisMemory.created_at.desc()).limit(500).all()

        if not rows:
            return []

        query_text = _build_scenario_text(symbol, diagnosis, {})
        corpus = [row.scenario_text for row in rows]

        # Try BM25
        try:
            from rank_bm25 import BM25Okapi
            tokenized_corpus = [doc.lower().split() for doc in corpus]
            bm25 = BM25Okapi(tokenized_corpus)
            query_tokens = query_text.lower().split()
            scores = bm25.get_scores(query_tokens)

            # Get top-N indices
            import numpy as np
            top_indices = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:limit]
        except ImportError:
            # Fallback: return most recent
            top_indices = list(range(min(limit, len(rows))))

        results = []
        for idx in top_indices:
            row = rows[idx]
            outcome = {}
            if row.outcome_json:
                try:
                    outcome = json.loads(row.outcome_json)
                except Exception:
                    pass

            results.append({
                "date": row.analysis_date,
                "symbol": row.symbol,
                "scenario": row.scenario_text[:120],
                "outcome": outcome.get("pnl_pct", "N/A"),
                "lesson": row.lessons_text[:100] if row.lessons_text else "",
            })

        return results

    except Exception as e:
        logger.warning(f"retrieve_similar({symbol}) failed: {e}")
        return []
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Record trade outcome
# ---------------------------------------------------------------------------

def record_outcome(memory_id: int, position_close_data: dict) -> bool:
    """
    Record the outcome of a closed trade against an analysis memory entry.

    Args:
        memory_id: ID of the AnalysisMemory record
        position_close_data: {pnl_pct, pnl_abs, hold_days, exit_price, exit_reason}

    Returns:
        True on success
    """
    from models import SessionLocal, AnalysisMemory

    db = SessionLocal()
    try:
        record = db.query(AnalysisMemory).filter(AnalysisMemory.id == memory_id).first()
        if not record:
            return False

        record.outcome_json = json.dumps(position_close_data, ensure_ascii=False)
        db.commit()
        return True
    except Exception as e:
        db.rollback()
        logger.warning(f"record_outcome({memory_id}) failed: {e}")
        return False
    finally:
        db.close()


# ---------------------------------------------------------------------------
# AI reflection on closed trade
# ---------------------------------------------------------------------------

def reflect_on_trade(memory_id: int) -> dict:
    """
    Trigger AI reflection on a completed trade to extract lessons.
    Background task — called after position close.

    Returns:
        {status, lessons}
    """
    from models import SessionLocal, AnalysisMemory
    from ai_analysis import call_ai

    db = SessionLocal()
    try:
        record = db.query(AnalysisMemory).filter(AnalysisMemory.id == memory_id).first()
        if not record:
            return {"status": "error", "lessons": "记录不存在"}

        try:
            analysis = json.loads(record.analysis_json)
        except Exception:
            analysis = {}

        try:
            outcome = json.loads(record.outcome_json) if record.outcome_json else {}
        except Exception:
            outcome = {}

        pnl = outcome.get("pnl_pct", "N/A")
        hold_days = outcome.get("hold_days", "N/A")
        exit_reason = outcome.get("exit_reason", "N/A")
        verdict_snippet = analysis.get("verdict", "")[:200]

        prompt = f"""你是一位有经验的交易教练，帮助交易者从过去的交易中学习。

交易标的: {record.symbol}
分析日期: {record.analysis_date}
当时的裁决: {verdict_snippet}

交易结果:
- 盈亏: {pnl}
- 持有天数: {hold_days}
- 退出原因: {exit_reason}

请提炼出1-3条具体可操作的交易教训。
格式：每条教训一行，以"•"开头，具体而不抽象。控制在150字以内。"""

        try:
            lessons = call_ai(prompt, complexity="standard", max_tokens=400)
        except Exception as e:
            lessons = f"[反思失败: {e}]"

        record.lessons_text = lessons
        db.commit()

        return {"status": "ok", "lessons": lessons}

    except Exception as e:
        db.rollback()
        logger.warning(f"reflect_on_trade({memory_id}) failed: {e}")
        return {"status": "error", "lessons": str(e)}
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Get recent analyses (for display)
# ---------------------------------------------------------------------------

def get_recent_analyses(symbol: str = None, limit: int = 10) -> list:
    """
    Retrieve recent analysis records, optionally filtered by symbol.
    """
    from models import SessionLocal, AnalysisMemory

    db = SessionLocal()
    try:
        q = db.query(AnalysisMemory)
        if symbol:
            q = q.filter(AnalysisMemory.symbol == symbol.upper())
        rows = q.order_by(AnalysisMemory.created_at.desc()).limit(limit).all()

        return [{
            "id": r.id,
            "symbol": r.symbol,
            "date": r.analysis_date,
            "has_outcome": r.outcome_json is not None,
            "has_lessons": r.lessons_text is not None,
            "lessons": r.lessons_text,
        } for r in rows]

    except Exception as e:
        logger.warning(f"get_recent_analyses failed: {e}")
        return []
    finally:
        db.close()
