"""
Goal-Driven Trading OS — FastAPI Application
Phase 1: 目标设定 + 仓位计算器 + 手动持仓 + 交易日志
"""
from datetime import datetime, timedelta
from pathlib import Path
import json
import time
import pandas as pd

# Load .env file (if present) before any os.getenv calls
try:
    from dotenv import load_dotenv
    _env_file = Path(__file__).resolve().parent.parent / ".env"
    if _env_file.exists():
        load_dotenv(_env_file)
except ImportError:
    pass

from fastapi import FastAPI, Depends, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, Response, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import text
from sqlalchemy.orm import Session

from models import (init_db, get_db, UserGoals, Position, TradeJournal, JournalCompliance,
                     StrategyConfig, BacktestRun, TradeSignal, StrategyLeaderboard,
                     AlertConfig, AlertHistory, ExecutionLog, ApiConfig, WatchlistItem, Base, engine)
from calculator import calculate_position_size, derive_constraints, check_can_open_position
from schemas import GoalsCreate, PositionCreate, CalculateRequest, PositionClose
from market_data import fetch_current_price, fetch_vix, detect_market_regime, fetch_stock_history, compute_technicals
from sync import sync_positions_from_broker
from stock_screener import SECTORS, diagnose_stock, screen_sector, build_combo
from ibkr_options import fetch_ibkr_options_chain, filter_options_for_sell_put
from strategy_library import get_library as get_strategy_library, filter_library, get_strategy_by_id
from strategy_hunter import compute_match_score, search_github_strategies, ai_generate_strategy
from scanner import scan_index, INDEX_MAP

app = FastAPI(title="Goal-Driven Trading OS", version="0.1.0")

BASE_DIR = Path(__file__).resolve().parent
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


def _normalize_goal_assets(
    asset_classes: str | None = None,
    assets: list[str] | None = None,
) -> str:
    """Accept both the v4 field name and the legacy checkbox list."""
    if asset_classes:
        return asset_classes

    assets = assets or []
    if not assets:
        return ""

    seen: list[str] = []
    for item in assets:
        if item not in seen:
            seen.append(item)
    return json.dumps(seen, ensure_ascii=True)


def _normalize_holding_period(
    holding_period: str | None = None,
    horizon: str | None = None,
) -> str:
    """Map old radio values to the canonical storage values."""
    value = holding_period or horizon or "days_weeks"
    mapping = {
        "swing": "days_weeks",
        "position": "weeks_months",
        "longterm": "months_year",
    }
    return mapping.get(value, value)


def _parse_asset_classes(asset_classes: str | None) -> list[str]:
    if not asset_classes:
        return []
    try:
        parsed = json.loads(asset_classes)
        if isinstance(parsed, list):
            return [str(item) for item in parsed]
    except Exception:
        pass
    return [item.strip() for item in asset_classes.split(",") if item.strip()]


@app.on_event("startup")
def startup():
    init_db()
    db = next(get_db())
    if not db.query(JournalCompliance).first():
        db.add(JournalCompliance())
        db.commit()
    # Seed default strategies
    from strategy_seeds import seed_strategies
    seed_strategies(db)
    db.close()
    # 启动定时任务
    from scheduler import init_scheduler
    init_scheduler()


@app.on_event("shutdown")
def shutdown():
    from scheduler import shutdown_scheduler
    shutdown_scheduler()


# ===== 策略参数中文标签 + 描述 =====
PARAM_LABELS = {
    "vix_min": "VIX 下限", "vix_max": "VIX 上限",
    "rsi_threshold": "RSI 阈值", "delta_target": "目标 Delta",
    "max_position_pct": "最大仓位比例",
    "profit_7d": "7天止盈", "profit_4w": "4周止盈", "profit_strong": "强止盈倍数",
    "force_close_dte": "强平剩余天数",
    "dte_target": "目标到期天数", "dte_min": "最短到期天数", "dte_max": "最长到期天数",
    "otm_pct": "虚值比例",
    "sma_200_above_pct": "SMA200 上方比例", "daily_dip_pct": "日跌幅阈值",
    "position_pct": "仓位比例", "exit_below_sma200_pct": "止损 SMA200 偏离",
    "dip_threshold": "回调阈值", "max_positions": "最大持仓笔数",
    "profit_0_4m": "0-4月止盈", "profit_4_6m": "4-6月止盈",
    "profit_7_9m": "7-9月止盈", "force_close_months": "强平月数",
    "delta_min": "Delta 下限", "delta_max": "Delta 上限",
    "min_safety_margin": "最小安全边际", "min_iv_rank": "最低 IV Rank",
    "max_sector_exposure": "板块敞口上限",
    "profit_target": "止盈目标", "stop_loss_pct": "止损比例",
    "time_stop_days": "时间止损(天)",
    "sma_short": "短均线周期", "sma_long": "长均线周期",
    "bb_period": "布林带周期", "bb_std": "布林带标准差", "bb_exit": "布林带出场位",
    "stop_loss_at_mult": "止损布林带倍数", "exit_at": "出场位置",
    "lookback_days": "回看天数", "score_threshold": "评分阈值",
    "min_score": "最低评分", "max_risk_pct": "最大风险比例",
}

PARAM_HINTS = {
    "vix_min": "低于此值市场太安逸，不触发。通常 12-20", "vix_max": "高于此值市场太恐慌，暂停。通常 25-35",
    "rsi_threshold": "RSI 低于此值视为超卖买入信号。通常 30-45", "delta_target": "期权 Delta 值，0.5=平值, 0.7=深度实值。通常 0.3-0.8",
    "max_position_pct": "单笔占总资金比例。如 0.05=5%", "position_pct": "单笔占总资金比例。如 0.20=20%",
    "profit_7d": "7天内达到此收益率则止盈。如 0.10=10%", "profit_4w": "4周内止盈目标",
    "profit_strong": "翻倍止盈倍数。1.0=翻倍", "force_close_dte": "到期前多少天强制平仓",
    "dte_target": "目标到期天数。LEAPS 通常 365, Sell Put 通常 30-45",
    "dte_min": "最短到期天数", "dte_max": "最长到期天数",
    "otm_pct": "虚值比例，如 0.05=比现价高5%的行权价",
    "sma_200_above_pct": "股价需在 SMA200 上方多少%才买入",
    "daily_dip_pct": "单日回调幅度触发，负数。如 -0.01=-1%",
    "exit_below_sma200_pct": "跌破 SMA200 多少%后止损退出",
    "dip_threshold": "回调幅度触发买入。如 -0.01=-1%",
    "max_positions": "同策略最多持有几笔",
    "profit_0_4m": "0-4个月止盈目标", "profit_4_6m": "4-6个月止盈目标", "profit_7_9m": "7-9个月止盈目标",
    "force_close_months": "持有超过几个月强制平仓",
    "delta_min": "Delta 下限(绝对值)，越小越虚值", "delta_max": "Delta 上限(绝对值)",
    "min_safety_margin": "最小安全边际(支撑位距现价%)。如 0.05=5%",
    "min_iv_rank": "最低隐含波动率排名(0-100)。高 IV 时卖 Put 权利金更高",
    "max_sector_exposure": "单板块最大敞口比例", "profit_target": "止盈目标比例。如 0.50=收到权利金的50%时平仓",
    "stop_loss_pct": "止损比例。负数。如 -1.50=亏损达权利金1.5倍时止损",
    "time_stop_days": "持有超过多少天未达标自动止盈/止损",
    "sma_short": "短均线天数，如 10", "sma_long": "长均线天数，如 20",
    "bb_period": "布林带计算周期天数", "bb_std": "布林带标准差倍数，通常 2.0",
    "bb_exit": "布林带出场位: mid=中轨, upper=上轨",
    "stop_loss_at_mult": "止损位=下轨再偏离几倍标准差",
    "exit_at": "出场位置: mid=中轨回归, upper=上轨突破",
}

# ===== 板块扫描缓存 =====
# {sector_key: {"html": rendered_html, "ts": timestamp, "sector_name": name}}
_scan_cache: dict = {}

# ===== 页面路由 =====

# ===== v4: 首页重定向到目标设定 =====

@app.get("/", response_class=RedirectResponse)
def home_redirect():
    return RedirectResponse("/goals", status_code=302)


# ===== [LEGACY] 交易机会 =====

@app.get("/legacy/opportunities", response_class=HTMLResponse)
def opportunities_page(request: Request, sector: str = "TECH", db: Session = Depends(get_db)):
    """交易机会：板块筛选 + AI 诊断 + 期权链"""
    goals = db.query(UserGoals).first()
    regime = detect_market_regime()
    # 直接把缓存 HTML 传入模板，避免页面加载后再发 HTMX 请求
    cached = _scan_cache.get(sector)
    cached_html = ""
    if cached:
        age_min = int((time.time() - cached["ts"]) / 60)
        cached_html = (
            f'<div class="text-xs text-gray-500 text-right mb-2">'
            f'上次更新: {age_min} 分钟前 · 点击「刷新数据」获取最新行情</div>'
            + cached["html"]
        )
    # 只显示 TECH（默认）+ 有缓存的板块；缓存板块附加机会数
    visible_sectors = {}
    for k, v in SECTORS.items():
        if k == "TECH" or k in _scan_cache:
            entry = dict(v)
            if k in _scan_cache:
                entry["opportunity_count"] = _scan_cache[k].get("count", len(v["symbols"]))
            else:
                entry["opportunity_count"] = None  # 尚未扫描
            visible_sectors[k] = entry
    # 活跃策略数（用于首页提示）
    active_configs = db.query(StrategyConfig).filter(StrategyConfig.is_active == True).all()
    return templates.TemplateResponse("opportunities.html", {
        "request": request,
        "sectors": visible_sectors,
        "current_sector": sector,
        "goals": goals,
        "regime": regime,
        "cached_html": cached_html,
        "has_strategies": bool(active_configs),
        "active_strategy_count": len(active_configs),
    })


# ===== 我的持仓 =====

@app.get("/legacy/positions", response_class=HTMLResponse)
def positions_page(request: Request, db: Session = Depends(get_db)):
    goals = db.query(UserGoals).order_by(UserGoals.updated_at.desc()).first()

    # Don't auto-sync on load (too slow). User clicks "刷新" button to sync.
    account = {}

    positions = db.query(Position).filter(Position.is_open == True).all()
    closed = db.query(Position).filter(Position.is_open == False).order_by(Position.close_date.desc()).limit(10).all()
    compliance = db.query(JournalCompliance).first()
    recent_journals = db.query(TradeJournal).order_by(TradeJournal.created_at.desc()).limit(5).all()

    constraints = None
    if goals:
        constraints = derive_constraints(goals.max_drawdown, goals.risk_per_trade)

    total_risk_pct = sum(p.risk_pct_of_account or 0 for p in positions)
    total_unrealized = sum(p.unrealized_pnl or 0 for p in positions)

    show_journal_reminder = False
    if compliance and compliance.trades_without_journal >= 3:
        show_journal_reminder = True

    regime = detect_market_regime()

    return templates.TemplateResponse("my_positions.html", {
        "request": request,
        "goals": goals,
        "constraints": constraints,
        "positions": positions,
        "closed_positions": closed,
        "total_risk_pct": total_risk_pct,
        "total_unrealized": total_unrealized,
        "account": account,
        "regime": regime,
        "show_journal_reminder": show_journal_reminder,
        "compliance": compliance,
        "recent_journals": recent_journals,
    })


# ===== 目标设定 =====

@app.post("/goals", response_class=HTMLResponse)
def set_goals(
    request: Request,
    annual_return_target: float = Form(...),
    max_drawdown: float = Form(...),
    risk_per_trade: float = Form(2.0),
    asset_classes: str = Form(""),
    holding_period: str = Form(""),
    assets: list[str] = Form([]),
    horizon: str = Form(""),
    db: Session = Depends(get_db),
):
    # 表单输入是百分比 (如 15), 模型存小数 (如 0.15)
    normalized_asset_classes = _normalize_goal_assets(asset_classes, assets)
    normalized_holding_period = _normalize_holding_period(holding_period, horizon)
    goals_data = GoalsCreate(
        annual_return_target=annual_return_target / 100,
        max_drawdown=max_drawdown / 100,
        risk_per_trade=risk_per_trade / 100,
    )
    constraints = derive_constraints(goals_data.max_drawdown, goals_data.risk_per_trade)

    goals = db.query(UserGoals).first()
    if goals:
        goals.annual_return_target = goals_data.annual_return_target
        goals.max_drawdown = goals_data.max_drawdown
        goals.risk_per_trade = goals_data.risk_per_trade
        goals.max_positions = constraints.max_positions
        goals.max_position_pct = constraints.max_position_pct
        goals.asset_classes = normalized_asset_classes
        goals.holding_period = normalized_holding_period
        goals.updated_at = datetime.utcnow()
    else:
        goals = UserGoals(
            annual_return_target=goals_data.annual_return_target,
            max_drawdown=goals_data.max_drawdown,
            risk_per_trade=goals_data.risk_per_trade,
            max_positions=constraints.max_positions,
            max_position_pct=constraints.max_position_pct,
            asset_classes=normalized_asset_classes,
            holding_period=normalized_holding_period,
        )
        db.add(goals)

    db.commit()
    db.refresh(goals)

    return templates.TemplateResponse("partials/goals_display.html", {
        "request": request,
        "goals": goals,
        "constraints": constraints,
    })


# ===== 仓位计算器 =====

@app.post("/calculate", response_class=HTMLResponse)
def calculate(
    request: Request,
    account_balance: float = Form(...),
    entry_price: float = Form(...),
    stop_loss: float = Form(...),
    risk_per_trade: float = Form(None),
    db: Session = Depends(get_db),
):
    goals = db.query(UserGoals).first()
    if risk_per_trade is None and goals:
        risk_per_trade = goals.risk_per_trade
    elif risk_per_trade is None:
        risk_per_trade = 0.02

    # Don't cap position value — risk is already controlled by risk_per_trade.
    # Position value depends on stock price and stop distance, not a fixed %.
    max_position_pct = 1.0

    result = calculate_position_size(
        account_balance=account_balance,
        entry_price=entry_price,
        stop_loss=stop_loss,
        risk_per_trade=risk_per_trade,
        max_position_pct=max_position_pct,
    )

    return templates.TemplateResponse("partials/calc_result.html", {
        "request": request,
        "result": result,
        "entry_price": entry_price,
        "stop_loss": stop_loss,
    })


# ===== 持仓管理 =====

@app.post("/positions", response_class=HTMLResponse)
def add_position(
    request: Request,
    symbol: str = Form(...),
    market: str = Form("stock"),
    entry_price: float = Form(...),
    stop_loss: float = Form(...),
    quantity: float = Form(...),
    account_balance: float = Form(...),
    entry_reason: str = Form(None),
    emotional_state: str = Form(None),
    vix_at_entry: float = Form(None),
    trend_at_entry: str = Form(None),
    db: Session = Depends(get_db),
):
    goals = db.query(UserGoals).first()
    if goals:
        open_count = db.query(Position).filter(Position.is_open == True).count()
        if not check_can_open_position(open_count, goals.max_positions):
            return HTMLResponse(
                content=f'<div class="text-red-600 p-4">已达持仓上限 ({goals.max_positions} 个)。需要先平仓才能开新仓。</div>',
                status_code=200,
            )

    risk_per_share = abs(entry_price - stop_loss)
    risk_amount = quantity * risk_per_share
    risk_pct = risk_amount / account_balance if account_balance > 0 else 0

    position = Position(
        symbol=symbol.upper(),
        market=market,
        entry_price=entry_price,
        stop_loss=stop_loss,
        quantity=quantity,
        risk_amount=round(risk_amount, 2),
        risk_pct_of_account=round(risk_pct, 4),
        account_balance_at_entry=account_balance,
    )
    db.add(position)

    # 日志合规追踪
    compliance = db.query(JournalCompliance).first()
    if compliance:
        compliance.total_trades += 1
        has_journal = bool(entry_reason)
        if has_journal:
            compliance.total_journaled += 1
            compliance.trades_without_journal = 0
        else:
            compliance.trades_without_journal += 1

    # 自动创建交易日志（如果填了理由）
    if entry_reason or emotional_state:
        journal = TradeJournal(
            symbol=symbol.upper(),
            action="buy",
            entry_reason=entry_reason,
            emotional_state=emotional_state,
            vix_at_entry=vix_at_entry,
            trend_at_entry=trend_at_entry,
        )
        db.add(journal)

    db.commit()

    # 回到持仓页，避免被新版 /positions 重定向到风险页。
    if request.headers.get("HX-Request"):
        return Response(status_code=200, headers={"HX-Redirect": "/legacy/positions"})
    return RedirectResponse(url="/legacy/positions", status_code=303)


@app.post("/positions/{position_id}/close", response_class=HTMLResponse)
def close_position(
    request: Request,
    position_id: int,
    close_price: float = Form(...),
    db: Session = Depends(get_db),
):
    position = db.query(Position).filter(Position.id == position_id).first()
    if not position:
        raise HTTPException(status_code=404, detail="持仓不存在")

    position.is_open = False
    position.close_price = close_price
    position.close_date = datetime.utcnow()
    db.commit()

    # 回到持仓页，避免被新版 /positions 重定向到风险页。
    if request.headers.get("HX-Request"):
        return Response(status_code=200, headers={"HX-Redirect": "/legacy/positions"})
    return RedirectResponse(url="/legacy/positions", status_code=303)


# ===== 交易日志 =====

@app.post("/journal", response_class=HTMLResponse)
def add_journal(
    request: Request,
    symbol: str = Form(...),
    action: str = Form(...),
    entry_reason: str = Form(None),
    market_conditions: str = Form(None),
    emotional_state: str = Form(None),
    vix_at_entry: float = Form(None),
    trend_at_entry: str = Form(None),
    notes: str = Form(None),
    position_id: int = Form(None),
    db: Session = Depends(get_db),
):
    journal = TradeJournal(
        symbol=symbol.upper(),
        action=action,
        entry_reason=entry_reason,
        market_conditions=market_conditions,
        emotional_state=emotional_state,
        vix_at_entry=vix_at_entry,
        trend_at_entry=trend_at_entry,
        notes=notes,
        position_id=position_id,
    )
    db.add(journal)

    compliance = db.query(JournalCompliance).first()
    if compliance:
        compliance.total_journaled += 1
        compliance.trades_without_journal = 0

    db.commit()

    recent = db.query(TradeJournal).order_by(TradeJournal.created_at.desc()).limit(5).all()
    return templates.TemplateResponse("partials/journal_list.html", {
        "request": request,
        "recent_journals": recent,
    })


# ===== Phase 1.5: Broker Sync + Market Data =====

@app.post("/sync-positions", response_class=HTMLResponse)
def sync_from_broker(request: Request, db: Session = Depends(get_db)):
    result = sync_positions_from_broker(db, with_pnl=True)  # Full sync with real-time P&L
    # HTMX 请求用 HX-Redirect 做客户端跳转，确保顶部统计卡片也更新
    if request.headers.get("HX-Request"):
        return Response(status_code=200, headers={"HX-Redirect": "/positions"})
    return RedirectResponse(url="/positions", status_code=303)


@app.get("/api/prices/{symbol}")
def get_price(symbol: str):
    return fetch_current_price(symbol)


@app.get("/api/vix")
def get_vix():
    return fetch_vix()


@app.get("/api/regime")
def get_regime():
    return detect_market_regime()


@app.get("/healthz")
def healthz(db: Session = Depends(get_db)):
    db.execute(text("SELECT 1"))
    return {"status": "ok"}


# ===== Phase 2: Strategies (will be populated next) =====

@app.get("/legacy/strategies", response_class=HTMLResponse)
def strategies_page(request: Request, db: Session = Depends(get_db)):
    configs = db.query(StrategyConfig).all()
    runs = db.query(BacktestRun).order_by(BacktestRun.created_at.desc()).limit(20).all()
    leaderboard = db.query(StrategyLeaderboard).order_by(StrategyLeaderboard.sharpe_ratio.desc()).all()
    goals = db.query(UserGoals).order_by(UserGoals.updated_at.desc()).first()
    regime = detect_market_regime()
    return templates.TemplateResponse("strategies.html", {
        "request": request,
        "configs": configs,
        "runs": runs,
        "leaderboard": leaderboard,
        "goals": goals,
        "regime": regime,
    })


@app.post("/strategies/discover", response_class=HTMLResponse)
def discover_strategies_endpoint(request: Request, db: Session = Depends(get_db)):
    """AI 自动搜索：遍历所有策略×参数×标的，找到符合目标的最佳策略"""
    goals = db.query(UserGoals).first()
    if not goals:
        return HTMLResponse('<div class="text-yellow-600 p-4">请先设定目标再搜索策略。</div>')

    from strategy_discovery import discover_strategies
    discovery = discover_strategies(goals, db)

    return templates.TemplateResponse("partials/discovery_result.html", {
        "request": request,
        "discovery": discovery,
        "goals": goals,
    })


@app.post("/strategies/configure", response_class=HTMLResponse)
def configure_strategy(
    request: Request,
    strategy_name: str = Form(...),
    symbol: str = Form("SPY"),
    params_yaml: str = Form("{}"),
    db: Session = Depends(get_db),
):
    config = StrategyConfig(
        strategy_name=strategy_name,
        symbol=symbol.upper(),
        params_yaml=params_yaml,
    )
    db.add(config)
    db.commit()
    configs = db.query(StrategyConfig).all()
    return templates.TemplateResponse("partials/strategy_configs.html", {
        "request": request,
        "configs": configs,
    })


@app.post("/strategies/{config_id}/backtest", response_class=HTMLResponse)
def run_backtest_endpoint(
    request: Request,
    config_id: int,
    start_date: str = Form(None),
    end_date: str = Form(None),
    db: Session = Depends(get_db),
):
    config = db.query(StrategyConfig).filter(StrategyConfig.id == config_id).first()
    if not config:
        raise HTTPException(status_code=404, detail="Strategy config not found")

    from backtester import run_full_backtest
    goals = db.query(UserGoals).first()
    result = run_full_backtest(
        config, goals, db,
        start_date=start_date or None,
        end_date=end_date or None,
    )

    return templates.TemplateResponse("partials/backtest_result.html", {
        "request": request,
        "result": result,
        "config": config,
    })


@app.post("/strategies/{config_id}/stress-test", response_class=HTMLResponse)
def run_stress_test_endpoint(request: Request, config_id: int, db: Session = Depends(get_db)):
    config = db.query(StrategyConfig).filter(StrategyConfig.id == config_id).first()
    if not config:
        raise HTTPException(status_code=404, detail="Strategy config not found")

    from backtester import run_stress_test
    results = run_stress_test(config, db)

    return templates.TemplateResponse("partials/stress_test_result.html", {
        "request": request,
        "results": results,
        "config": config,
    })


@app.get("/legacy/strategies/match", response_class=HTMLResponse)
def match_strategies(request: Request, db: Session = Depends(get_db)):
    goals = db.query(UserGoals).first()
    if not goals:
        return HTMLResponse('<div class="text-yellow-600 p-4">请先设定目标再匹配策略。</div>')

    from strategy_matcher import match_strategies_to_goals
    matches = match_strategies_to_goals(goals, db)

    return templates.TemplateResponse("partials/match_result.html", {
        "request": request,
        "matches": matches,
        "goals": goals,
    })


@app.get("/legacy/strategies/leaderboard", response_class=HTMLResponse)
def leaderboard_page(request: Request, db: Session = Depends(get_db)):
    leaderboard = db.query(StrategyLeaderboard).order_by(StrategyLeaderboard.sharpe_ratio.desc()).all()
    return templates.TemplateResponse("partials/leaderboard_table.html", {
        "request": request,
        "leaderboard": leaderboard,
    })


@app.post("/strategies/leaderboard/refresh", response_class=HTMLResponse)
def refresh_leaderboard(request: Request, db: Session = Depends(get_db)):
    from strategy_matcher import refresh_leaderboard
    refresh_leaderboard(db)
    leaderboard = db.query(StrategyLeaderboard).order_by(StrategyLeaderboard.sharpe_ratio.desc()).all()
    return templates.TemplateResponse("partials/leaderboard_table.html", {
        "request": request,
        "leaderboard": leaderboard,
    })


# ===== 策略管理 (CRUD) =====

@app.get("/legacy/strategies/manage", response_class=HTMLResponse)
def strategy_manage_page(request: Request, db: Session = Depends(get_db)):
    configs = db.query(StrategyConfig).order_by(StrategyConfig.is_active.desc(), StrategyConfig.strategy_name).all()
    return templates.TemplateResponse("strategy_manage.html", {
        "request": request,
        "configs": configs,
    })


@app.get("/legacy/strategies/edit/{config_id}", response_class=HTMLResponse)
def strategy_edit_page(request: Request, config_id: int, db: Session = Depends(get_db)):
    config = db.query(StrategyConfig).filter(StrategyConfig.id == config_id).first()
    if not config:
        raise HTTPException(status_code=404)
    import json
    params = json.loads(config.params_yaml) if config.params_yaml else {}
    # 为每个参数附带中文标签和类型信息
    param_items = []
    for key, value in params.items():
        label = PARAM_LABELS.get(key, key)
        if isinstance(value, bool):
            ptype = "bool"
        elif isinstance(value, int):
            ptype = "int"
        elif isinstance(value, float):
            ptype = "float"
        else:
            ptype = "str"
        hint = PARAM_HINTS.get(key, "")
        param_items.append({"key": key, "label": label, "value": value, "type": ptype, "hint": hint})
    # 所有可选参数供「添加参数」下拉使用
    all_param_options = dict(sorted(
        {k: {"label": PARAM_LABELS.get(k, k), "hint": v} for k, v in PARAM_HINTS.items() if k not in params}.items(),
        key=lambda x: x[1]["label"]
    ))
    return templates.TemplateResponse("strategy_edit.html", {
        "request": request,
        "config": config,
        "params": params,
        "param_items": param_items,
        "all_param_options": all_param_options,
    })


@app.post("/strategies/save/{config_id}", response_class=HTMLResponse)
async def strategy_save(
    request: Request,
    config_id: int,
    db: Session = Depends(get_db),
):
    config = db.query(StrategyConfig).filter(StrategyConfig.id == config_id).first()
    if not config:
        raise HTTPException(status_code=404)

    form = await request.form()
    config.display_name = form.get("display_name", config.display_name)
    config.description = form.get("description", "")
    config.symbol_pool = form.get("symbol_pool", "")
    config.direction = form.get("direction", "bullish")
    config.instrument = form.get("instrument", "stock")
    config.is_active = form.get("is_active", "true") == "true"

    # 从结构化表单字段重建 params JSON
    import json
    old_params = json.loads(config.params_yaml) if config.params_yaml else {}
    new_params = {}
    for key in list(form.keys()):
        if key.startswith("param_"):
            param_name = key[6:]  # 去掉 "param_" 前缀
            raw_value = form.get(key, "")
            # 保持原始类型
            old_val = old_params.get(param_name)
            if isinstance(old_val, bool):
                new_params[param_name] = raw_value.lower() in ("true", "1", "yes")
            elif isinstance(old_val, int):
                try:
                    new_params[param_name] = int(float(raw_value))
                except (ValueError, TypeError):
                    new_params[param_name] = old_val
            elif isinstance(old_val, float):
                try:
                    new_params[param_name] = float(raw_value)
                except (ValueError, TypeError):
                    new_params[param_name] = old_val
            else:
                new_params[param_name] = raw_value

    config.params_yaml = json.dumps(new_params, ensure_ascii=False)
    db.commit()

    # 显示保存成功提示，1秒后返回上一页（不刷新列表）
    return HTMLResponse(
        '<span class="text-accent-green text-sm">已保存</span>'
        '<script>setTimeout(function(){window.history.back()},800)</script>'
    )


@app.post("/strategies/toggle/{config_id}", response_class=HTMLResponse)
def strategy_toggle(request: Request, config_id: int, db: Session = Depends(get_db)):
    config = db.query(StrategyConfig).filter(StrategyConfig.id == config_id).first()
    if config:
        config.is_active = not config.is_active
        db.commit()
    configs = db.query(StrategyConfig).order_by(StrategyConfig.is_active.desc(), StrategyConfig.strategy_name).all()
    return templates.TemplateResponse("partials/strategy_manage_list.html", {"request": request, "configs": configs})


@app.post("/strategies/create", response_class=HTMLResponse)
def strategy_create(
    request: Request,
    display_name: str = Form(...),
    strategy_name: str = Form("custom"),
    description: str = Form(""),
    symbol_pool: str = Form(""),
    direction: str = Form("bullish"),
    instrument: str = Form("stock"),
    db: Session = Depends(get_db),
):
    import re
    code_name = re.sub(r'[^a-z0-9_]', '_', display_name.lower().replace(' ', '_'))[:30]
    config = StrategyConfig(
        strategy_name=code_name,
        display_name=display_name,
        description=description,
        symbol_pool=symbol_pool,
        direction=direction,
        instrument=instrument,
        params_yaml="{}",
        is_active=True,
    )
    db.add(config)
    db.commit()
    configs = db.query(StrategyConfig).order_by(StrategyConfig.is_active.desc(), StrategyConfig.strategy_name).all()
    return templates.TemplateResponse("partials/strategy_manage_list.html", {"request": request, "configs": configs})


# ===== 策略发现 + AI 研究 =====

@app.get("/legacy/strategies/discover", response_class=HTMLResponse)
def strategy_discover_page(
    request: Request,
    instrument: str = None,
    direction: str = None,
    style: str = None,
    risk_level: str = None,
    min_return: str = None,   # accept str to handle empty string from filter links
    db: Session = Depends(get_db),
):
    """策略发现：从经过验证的策略库中找到适合你目标的策略"""
    from strategy_library import filter_library

    # convert min_return: "" or None → None, valid int string → int
    min_return_int = None
    if min_return:
        try:
            min_return_int = int(min_return)
        except (ValueError, TypeError):
            min_return_int = None

    strategies = filter_library(
        instrument=instrument or None,
        direction=direction or None,
        style=style or None,
        risk_level=risk_level or None,
        min_return=min_return_int,
    )

    # Check which library strategies are already adopted (by matching strategy_name with library id)
    existing_ids = set()
    for cfg in db.query(StrategyConfig).all():
        existing_ids.add(cfg.strategy_name)

    return templates.TemplateResponse("strategy_discover.html", {
        "request": request,
        "strategies": strategies,
        "existing_ids": existing_ids,
        "current_instrument": instrument or "all",
        "current_direction": direction or "all",
        "current_style": style or "all",
        "current_risk": risk_level or "all",
        "current_min_return": min_return or 0,
    })


@app.post("/strategies/adopt/{strategy_id}", response_class=HTMLResponse)
def strategy_adopt(request: Request, strategy_id: str, db: Session = Depends(get_db)):
    """从策略库采纳一个策略到我的策略配置"""
    from strategy_library import get_strategy_by_id
    import json

    lib_strategy = get_strategy_by_id(strategy_id)
    if not lib_strategy:
        return HTMLResponse(
            f'<div class="discover-card bg-dark-700 rounded-xl border border-red-500/40 p-5">'
            f'<p class="text-accent-red text-sm">策略 {strategy_id} 不存在</p></div>'
        )

    # Check if already adopted
    existing = db.query(StrategyConfig).filter(StrategyConfig.strategy_name == strategy_id).first()
    if existing:
        return HTMLResponse(
            f'<div class="discover-card bg-dark-700 rounded-xl border border-accent-green/30 p-5">'
            f'<p class="text-accent-green text-sm">✓ 已采纳「{lib_strategy["name"]}」</p>'
            f'<a href="/strategies/manage" class="text-xs text-gray-400 hover:text-white underline mt-1 block">前往策略管理 →</a></div>'
        )

    config = StrategyConfig(
        strategy_name=strategy_id,
        display_name=lib_strategy["name"],
        description=lib_strategy.get("description", ""),
        direction=lib_strategy.get("direction", "neutral"),
        instrument=lib_strategy.get("instrument", "stock"),
        params_yaml=json.dumps(lib_strategy.get("params", {}), ensure_ascii=False),
        is_active=True,
    )
    db.add(config)
    db.commit()

    return HTMLResponse(
        f'<div class="discover-card bg-dark-700 rounded-xl border border-accent-green/40 p-5">'
        f'<p class="text-accent-green font-semibold">✓ 已添加「{lib_strategy["name"]}」</p>'
        f'<p class="text-xs text-gray-400 mt-1">策略已加入你的策略列表</p>'
        f'<a href="/strategies/manage" class="text-xs text-accent-blue hover:text-white underline mt-2 block">前往策略管理 →</a></div>'
    )


@app.get("/legacy/strategies/research", response_class=HTMLResponse)
def strategy_research_page(request: Request, db: Session = Depends(get_db)):
    """AI 策略研究：告诉我你的目标，我帮你找有效策略并验证"""
    return templates.TemplateResponse("strategy_research.html", {
        "request": request,
    })


@app.post("/strategies/research/run", response_class=HTMLResponse)
async def strategy_research_run(
    request: Request,
    instrument: str = Form("any"),
    direction: str = Form("any"),
    min_annual_return: float = Form(20),
    risk_level: str = Form("any"),
    extra_notes: str = Form(""),
    db: Session = Depends(get_db),
):
    """运行 AI 策略研究管道"""
    from strategy_researcher import search_strategies_for_requirements

    min_return_decimal = min_annual_return / 100

    results = await search_strategies_for_requirements(
        instrument=instrument,
        direction=direction,
        min_annual_return=min_return_decimal,
        risk_level=risk_level,
        extra_notes=extra_notes,
    )

    # Check which are already adopted
    existing_ids = set(cfg.strategy_name for cfg in db.query(StrategyConfig).all())

    return templates.TemplateResponse("partials/research_results.html", {
        "request": request,
        "results": results,
        "existing_ids": existing_ids,
        "min_annual_return": min_annual_return,
    })


@app.post("/strategies/research/adopt", response_class=HTMLResponse)
async def strategy_research_adopt(
    request: Request,
    db: Session = Depends(get_db),
):
    """从 AI 研究结果采纳策略"""
    import json
    form = await request.form()
    strategy_json = form.get("strategy_json", "{}")

    try:
        strategy = json.loads(strategy_json)
    except (json.JSONDecodeError, TypeError):
        return HTMLResponse('<div class="text-accent-red text-sm p-2">无法解析策略数据</div>')

    strategy_id = strategy.get("id", "")
    strategy_name = strategy.get("name", "未知策略")

    if not strategy_id:
        return HTMLResponse('<div class="text-accent-red text-sm p-2">策略 ID 缺失</div>')

    # Check if already adopted
    existing = db.query(StrategyConfig).filter(StrategyConfig.strategy_name == strategy_id).first()
    if existing:
        return HTMLResponse(
            f'<span class="text-accent-green text-sm font-semibold">✓ 已添加「{strategy_name}」</span>'
            f'<a href="/strategies/manage" class="text-xs text-gray-400 hover:text-white underline ml-2">管理策略 →</a>'
        )

    desc = strategy.get("description", "")
    source = strategy.get("source", "")
    if source:
        desc = f"[来源: {source}] {desc}"

    config = StrategyConfig(
        strategy_name=strategy_id,
        display_name=strategy_name,
        description=f"[AI 研究] {desc}",
        direction=strategy.get("direction", "neutral"),
        instrument=strategy.get("instrument", "stock"),
        params_yaml=json.dumps(strategy.get("params", {}), ensure_ascii=False),
        is_active=True,
    )
    db.add(config)
    db.commit()

    return HTMLResponse(
        f'<span class="text-accent-green text-sm font-semibold">✓ 已添加「{strategy_name}」</span>'
        f'<a href="/strategies/manage" class="text-xs text-gray-400 hover:text-white underline ml-2">管理策略 →</a>'
    )


# ===== 标的筛选 + AI 诊断 + 组合推荐 + 期权链 =====

@app.get("/legacy/screener")
def screener_page(sector: str = "TECH"):
    """旧 URL 兼容：重定向到首页"""
    return RedirectResponse(url=f"/?sector={sector}", status_code=301)


@app.get("/screener/cached/{sector}", response_class=HTMLResponse)
def get_cached_scan(request: Request, sector: str):
    """返回缓存的扫描结果（秒开），没缓存就返回提示"""
    cached = _scan_cache.get(sector)
    if cached:
        age_min = int((time.time() - cached["ts"]) / 60)
        return HTMLResponse(
            f'<div class="text-xs text-gray-500 text-right mb-2">'
            f'上次更新: {age_min} 分钟前 · 点击「刷新数据」获取最新行情</div>'
            + cached["html"]
        )
    return HTMLResponse(
        '<div class="text-center py-16">'
        '<div class="text-gray-400 mb-2">尚无缓存数据</div>'
        '<div class="text-sm text-gray-500">点击上方「刷新数据」按钮开始扫描</div>'
        '</div>'
    )


@app.post("/screener/scan", response_class=HTMLResponse)
def scan_sector(request: Request, sector: str = Form("TECH"), db: Session = Depends(get_db)):
    goals = db.query(UserGoals).first()

    # Use multi-strategy opportunity engine if goals set
    from opportunity_engine import find_opportunities
    import json as _json
    account_balance = 100000
    if goals:
        from broker import fetch_account_info
        acct = fetch_account_info()
        if "equity" in acct:
            account_balance = acct["equity"]

    # 加载用户启用的策略配置
    active_configs = db.query(StrategyConfig).filter(StrategyConfig.is_active == True).all()
    strategy_configs = [
        {
            "id": cfg.id,
            "strategy_name": cfg.strategy_name,
            "display_name": cfg.display_name or cfg.strategy_name,
            "instrument": cfg.instrument,
            "direction": cfg.direction or "neutral",
            "params": _json.loads(cfg.params_yaml or "{}"),
        }
        for cfg in active_configs
    ]

    opps = find_opportunities(
        goals_return=goals.annual_return_target if goals else 0.15,
        goals_drawdown=goals.max_drawdown if goals else 0.10,
        risk_per_trade=goals.risk_per_trade if goals else 0.02,
        account_balance=account_balance,
        sectors=[sector],
        strategy_configs=strategy_configs if strategy_configs else None,
    )

    # Also get stock diagnostics for the table
    results = screen_sector(sector)

    sector_name = SECTORS.get(sector, {}).get("name", sector)
    tpl_ctx = {
        "request": request,
        "results": results,
        "opportunities": opps.get("opportunities", [])[:15],
        "combos": opps.get("combos", [])[:3],
        "total_strategies": opps.get("total_strategies", 0),
        "total_compatible": opps.get("total_compatible", 0),
        "sector_name": sector_name,
        "has_strategies": bool(strategy_configs),
        "active_strategy_count": len(strategy_configs),
    }
    resp = templates.TemplateResponse("partials/screener_results.html", tpl_ctx)

    # 缓存渲染后的 HTML
    import io
    body = resp.body.decode("utf-8") if isinstance(resp.body, bytes) else resp.body
    opp_count = len(opps.get("opportunities", []))
    _scan_cache[sector] = {"html": body, "ts": time.time(), "sector_name": sector_name, "count": opp_count}

    return resp


@app.get("/diagnose/{symbol}", response_class=HTMLResponse)
def diagnose_page(request: Request, symbol: str, db: Session = Depends(get_db)):
    diag = diagnose_stock(symbol.upper())
    # Fetch options chain
    options = fetch_ibkr_options_chain(symbol.upper(), right="P", dte_min=20, dte_max=60)
    sell_put_options = filter_options_for_sell_put(options, diag.current_price)
    return templates.TemplateResponse("diagnose.html", {
        "request": request,
        "diag": diag,
        "options": sell_put_options[:10],
        "all_options": options[:20],
    })


@app.get("/api/diagnose/{symbol}")
def diagnose_api(symbol: str):
    diag = diagnose_stock(symbol.upper())
    return {
        "symbol": diag.symbol, "price": diag.current_price, "score": diag.score,
        "trend": diag.trend, "support": diag.support_level, "safety_margin": diag.safety_margin,
        "recommendation": diag.recommendation, "suggested_strike": diag.suggested_strike,
    }


@app.get("/api/ai-analyze/{symbol}", response_class=HTMLResponse)
def ai_analyze(request: Request, symbol: str):
    """AI 智能分析一只标的"""
    from ai_analysis import analyze_stock
    diag = diagnose_stock(symbol.upper())
    diag_dict = {
        "current_price": diag.current_price, "trend": diag.trend,
        "rsi": diag.rsi, "support_level": diag.support_level,
        "safety_margin": diag.safety_margin, "score": diag.score,
    }
    result = analyze_stock(symbol.upper(), diag_dict)
    if result.get("analysis"):
        analysis_html = result["analysis"].replace("\n", "<br>")
        provider = result.get("provider", "unknown")
        return HTMLResponse(f'<div class="bg-dark-800 rounded-lg p-4 border border-accent-blue/30"><div class="text-xs text-accent-blue mb-2">AI 分析 ({provider})</div><div class="text-sm text-gray-300 leading-relaxed">{analysis_html}</div></div>')
    else:
        error = result.get("error", "未知错误")
        return HTMLResponse(f'<div class="bg-dark-800 rounded-lg p-3 text-xs text-accent-yellow">{error}</div>')


@app.get("/api/options/{symbol}")
def options_chain_api(symbol: str, right: str = "P", dte_min: int = 20, dte_max: int = 60):
    options = fetch_ibkr_options_chain(symbol.upper(), right, dte_min, dte_max)
    return [{"strike": o.strike, "expiry": o.expiry, "delta": o.delta, "iv": o.iv,
             "bid": o.bid, "ask": o.ask, "mid": o.mid, "dte": o.dte, "code": o.contract_code}
            for o in options[:30]]


# ===== Phase 3: Multi-Market =====

@app.get("/legacy/portfolio", response_class=HTMLResponse)
def portfolio_page(request: Request, db: Session = Depends(get_db)):
    positions = db.query(Position).filter(Position.is_open == True).all()
    goals = db.query(UserGoals).first()
    regime = detect_market_regime()

    by_market = {}
    for p in positions:
        by_market.setdefault(p.market, []).append(p)

    total_risk_pct = sum(p.risk_pct_of_account or 0 for p in positions)

    return templates.TemplateResponse("portfolio.html", {
        "request": request,
        "positions": positions,
        "by_market": by_market,
        "goals": goals,
        "regime": regime,
        "total_risk_pct": total_risk_pct,
    })


# ===== 交易 (merged: execution + journal + calculator) =====

@app.get("/legacy/trade", response_class=HTMLResponse)
def trade_page(request: Request, db: Session = Depends(get_db)):
    pending = db.query(TradeSignal).filter(TradeSignal.status == "pending").all()
    confirmed = db.query(TradeSignal).filter(TradeSignal.status == "confirmed").all()
    recent_executed = db.query(TradeSignal).filter(TradeSignal.status == "executed").order_by(TradeSignal.execution_time.desc()).limit(10).all()
    goals = db.query(UserGoals).first()
    recent_journals = db.query(TradeJournal).order_by(TradeJournal.created_at.desc()).limit(5).all()
    return templates.TemplateResponse("trade.html", {
        "request": request,
        "pending": pending,
        "signals": pending,
        "confirmed": confirmed,
        "recent_executed": recent_executed,
        "goals": goals,
        "recent_journals": recent_journals,
    })

# Keep /execution as alias
@app.get("/legacy/execution", response_class=HTMLResponse)
def execution_page(request: Request, db: Session = Depends(get_db)):
    return trade_page(request, db)


@app.post("/execution/generate", response_class=HTMLResponse)
def generate_signals(request: Request, db: Session = Depends(get_db)):
    from execution import generate_pending_signals
    count = generate_pending_signals(db)
    pending = db.query(TradeSignal).filter(TradeSignal.status == "pending").all()
    return templates.TemplateResponse("partials/signal_list.html", {
        "request": request,
        "signals": pending,
        "generated_count": count,
    })


@app.post("/signals/{signal_id}/confirm", response_class=HTMLResponse)
def confirm_signal(request: Request, signal_id: int, db: Session = Depends(get_db)):
    signal = db.query(TradeSignal).filter(TradeSignal.id == signal_id).first()
    if signal:
        signal.status = "confirmed"
        db.commit()
    pending = db.query(TradeSignal).filter(TradeSignal.status.in_(["pending", "confirmed"])).all()
    return templates.TemplateResponse("partials/signal_list.html", {
        "request": request,
        "signals": pending,
    })


@app.post("/signals/{signal_id}/skip", response_class=HTMLResponse)
def skip_signal(request: Request, signal_id: int, db: Session = Depends(get_db)):
    signal = db.query(TradeSignal).filter(TradeSignal.id == signal_id).first()
    if signal:
        signal.status = "skipped"
        db.commit()
    pending = db.query(TradeSignal).filter(TradeSignal.status.in_(["pending", "confirmed"])).all()
    return templates.TemplateResponse("partials/signal_list.html", {
        "request": request,
        "signals": pending,
    })


@app.post("/signals/{signal_id}/execute", response_class=HTMLResponse)
def execute_signal(request: Request, signal_id: int, db: Session = Depends(get_db)):
    from execution import execute_confirmed_signal
    result = execute_confirmed_signal(signal_id, db)
    pending = db.query(TradeSignal).filter(TradeSignal.status.in_(["pending", "confirmed"])).all()
    return templates.TemplateResponse("partials/signal_list.html", {
        "request": request,
        "signals": pending,
        "execute_result": result,
    })


# ===== 交易记录 =====

@app.get("/legacy/history", response_class=HTMLResponse)
def history_page(request: Request, db: Session = Depends(get_db)):
    from performance import compute_portfolio_performance
    perf = compute_portfolio_performance(db)
    recent_journals = db.query(TradeJournal).order_by(TradeJournal.created_at.desc()).limit(20).all()
    closed = db.query(Position).filter(Position.is_open == False).order_by(Position.close_date.desc()).limit(20).all()
    return templates.TemplateResponse("history.html", {
        "request": request,
        "perf": perf,
        "recent_journals": recent_journals,
        "closed_positions": closed,
    })

# Keep old URL as alias
@app.get("/legacy/performance", response_class=HTMLResponse)
def performance_page(request: Request, db: Session = Depends(get_db)):
    return history_page(request, db)


# ===== Phase 5: Risk + Alerts =====

@app.get("/legacy/risk", response_class=HTMLResponse)
def risk_page(request: Request, db: Session = Depends(get_db)):
    from risk_engine import compute_portfolio_risk
    risk = compute_portfolio_risk(db)
    alert_config = db.query(AlertConfig).first()
    recent_alerts = db.query(AlertHistory).order_by(AlertHistory.created_at.desc()).limit(10).all()
    return templates.TemplateResponse("risk.html", {
        "request": request,
        "risk": risk,
        "alert_config": alert_config,
        "recent_alerts": recent_alerts,
    })


@app.get("/legacy/alerts/config", response_class=HTMLResponse)
def alerts_config_page(request: Request, db: Session = Depends(get_db)):
    config = db.query(AlertConfig).first()
    return templates.TemplateResponse("alerts_config.html", {
        "request": request,
        "config": config,
    })


@app.post("/alerts/config", response_class=HTMLResponse)
def save_alerts_config(
    request: Request,
    feishu_webhook_url: str = Form(None),
    sms_enabled: bool = Form(False),
    sms_phone: str = Form(None),
    drawdown_warn_pct: float = Form(5),
    drawdown_critical_pct: float = Form(8),
    single_position_loss_pct: float = Form(3),
    rate_limit_minutes: int = Form(60),
    db: Session = Depends(get_db),
):
    config = db.query(AlertConfig).first()
    if not config:
        config = AlertConfig()
        db.add(config)

    config.feishu_webhook_url = feishu_webhook_url
    config.sms_enabled = sms_enabled
    config.sms_phone = sms_phone
    config.drawdown_warn_pct = drawdown_warn_pct / 100
    config.drawdown_critical_pct = drawdown_critical_pct / 100
    config.single_position_loss_pct = single_position_loss_pct / 100
    config.rate_limit_minutes = rate_limit_minutes
    db.commit()

    return templates.TemplateResponse("partials/alert_config_saved.html", {
        "request": request,
        "config": config,
    })


@app.post("/alerts/test", response_class=HTMLResponse)
def test_alert(request: Request, db: Session = Depends(get_db)):
    from alerts import send_alert
    result = send_alert(db, "test", "测试告警", "这是一条测试告警消息。如果你收到了，告警配置正确。")
    return HTMLResponse(f'<div class="p-3 text-sm {"text-green-600" if result.get("delivered") else "text-red-600"}">{result.get("message", "发送完成")}</div>')


@app.get("/legacy/alerts/history", response_class=HTMLResponse)
def alerts_history(request: Request, db: Session = Depends(get_db)):
    alerts = db.query(AlertHistory).order_by(AlertHistory.created_at.desc()).limit(50).all()
    return templates.TemplateResponse("alerts_history.html", {
        "request": request,
        "alerts": alerts,
    })


@app.post("/risk/check", response_class=HTMLResponse)
def check_risk(request: Request, db: Session = Depends(get_db)):
    from alerts import check_and_fire_alerts
    fired = check_and_fire_alerts(db)
    return HTMLResponse(f'<div class="p-3 text-sm text-blue-600">检查完成。触发了 {len(fired)} 条告警。</div>')


# ===== 设置：API 配置 =====

API_SERVICES = [
    {"name": "ibkr", "display": "IBKR 盈透证券 (美股/期权)", "desc": "通过 TWS 或 IB Gateway 连接。用于同步持仓、获取行情、执行交易。默认 Paper Trading 端口 7497。", "fields": ["Host (默认 127.0.0.1)", "Port (默认 7497)"], "env_keys": ["IBKR_HOST", "IBKR_PORT"]},
    {"name": "ccxt_binance", "display": "Binance (加密货币)", "desc": "获取加密货币行情和交易。公开行情不需要 API Key。", "fields": ["API Key", "Secret Key"], "env_keys": ["CCXT_BINANCE_API_KEY", "CCXT_BINANCE_SECRET"]},
    {"name": "ccxt_okx", "display": "OKX (加密货币)", "desc": "获取 OKX 交易所行情和交易数据。", "fields": ["API Key", "Secret Key"], "env_keys": ["CCXT_OKX_API_KEY", "CCXT_OKX_SECRET"]},
    {"name": "deepseek", "display": "DeepSeek (AI 分析, 推荐)", "desc": "用于 AI 智能分析标的，生成交易建议。免费额度充足，延迟低。", "fields": ["API Key"], "env_keys": ["DEEPSEEK_API_KEY"]},
    {"name": "anthropic", "display": "Claude (AI 分析)", "desc": "Anthropic Claude 模型，分析质量最高。", "fields": ["API Key"], "env_keys": ["ANTHROPIC_API_KEY"]},
    {"name": "openai", "display": "ChatGPT (AI 分析)", "desc": "OpenAI GPT-4o 模型。", "fields": ["API Key"], "env_keys": ["OPENAI_API_KEY"]},
    {"name": "gemini", "display": "Google Gemini (AI 分析)", "desc": "Google Gemini 模型，免费额度大。", "fields": ["API Key"], "env_keys": ["GEMINI_API_KEY"]},
    {"name": "feishu", "display": "飞书 (告警通知)", "desc": "通过飞书机器人 Webhook 接收风险告警推送。", "fields": ["Webhook URL"], "env_keys": ["FEISHU_WEBHOOK_URL"]},
    {"name": "twilio", "display": "Twilio (短信告警)", "desc": "通过短信接收风险告警。需要 Twilio 账号。", "fields": ["Account SID", "Auth Token", "发送号码", "接收号码"], "env_keys": ["TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_FROM_NUMBER", "TWILIO_TO_NUMBER"]},
    {"name": "fred", "display": "FRED (美联储宏观数据)", "desc": "获取 GDP、CPI、利率、收益率曲线等宏观指标。免费，注册 fred.stlouisfed.org 获取。", "fields": ["API Key"], "env_keys": ["FRED_API_KEY"]},
    {"name": "finnhub", "display": "Finnhub (公司新闻)", "desc": "获取个股新闻资讯。免费 60次/分钟，注册 finnhub.io 获取。", "fields": ["API Key"], "env_keys": ["FINNHUB_API_KEY"]},
]


@app.get("/legacy/settings", response_class=HTMLResponse)
def settings_page(request: Request, db: Session = Depends(get_db)):
    configs = {}
    for svc in API_SERVICES:
        cfg = db.query(ApiConfig).filter(ApiConfig.service_name == svc["name"]).first()
        configs[svc["name"]] = cfg
    alert_cfg = db.query(AlertConfig).first()
    goals = db.query(UserGoals).first()
    return templates.TemplateResponse("settings.html", {
        "request": request,
        "services": API_SERVICES,
        "configs": configs,
        "alert_config": alert_cfg,
        "goals": goals,
    })


@app.post("/settings/api/{service_name}", response_class=HTMLResponse)
def save_api_config(
    request: Request,
    service_name: str,
    db: Session = Depends(get_db),
    api_key: str = Form(None),
    api_secret: str = Form(None),
    extra_1: str = Form(None),
    extra_2: str = Form(None),
):
    import json, os
    cfg = db.query(ApiConfig).filter(ApiConfig.service_name == service_name).first()
    if not cfg:
        svc = next((s for s in API_SERVICES if s["name"] == service_name), None)
        cfg = ApiConfig(service_name=service_name, display_name=svc["display"] if svc else service_name)
        db.add(cfg)

    cfg.api_key = api_key
    cfg.api_secret = api_secret
    cfg.extra_config = json.dumps({"extra_1": extra_1, "extra_2": extra_2}) if extra_1 or extra_2 else None
    cfg.is_active = bool(api_key)
    cfg.status = "已配置" if api_key else "未配置"

    # Write to environment for immediate use
    svc = next((s for s in API_SERVICES if s["name"] == service_name), None)
    if svc and api_key:
        os.environ[svc["env_keys"][0]] = api_key
        if api_secret and len(svc["env_keys"]) > 1:
            os.environ[svc["env_keys"][1]] = api_secret
        if extra_1 and len(svc["env_keys"]) > 2:
            os.environ[svc["env_keys"][2]] = extra_1
        if extra_2 and len(svc["env_keys"]) > 3:
            os.environ[svc["env_keys"][3]] = extra_2

    db.commit()
    return HTMLResponse(f'<div class="text-accent-green text-xs py-2">{cfg.display_name} 配置已保存</div>')


# ===== K线图数据 API =====

@app.get("/api/chart/{symbol}")
def chart_data_api(symbol: str, period: str = "1y"):
    """返回 K 线图数据（lightweight-charts 格式）"""
    df = fetch_stock_history(symbol.upper(), period=period)
    if df.empty:
        return {"error": f"No data for {symbol}", "candles": [], "volumes": []}

    df = compute_technicals(df)
    candles = []
    volumes = []
    sma20 = []
    sma50 = []
    sma200 = []

    for idx, row in df.iterrows():
        ts = int(idx.timestamp())
        candles.append({
            "time": ts, "open": round(row["open"], 2),
            "high": round(row["high"], 2), "low": round(row["low"], 2),
            "close": round(row["close"], 2),
        })
        color = "rgba(34,197,94,0.3)" if row["close"] >= row["open"] else "rgba(239,68,68,0.3)"
        volumes.append({"time": ts, "value": int(row["volume"]), "color": color})

        if pd.notna(row.get("sma_20")):
            sma20.append({"time": ts, "value": round(row["sma_20"], 2)})
        if pd.notna(row.get("sma_50")):
            sma50.append({"time": ts, "value": round(row["sma_50"], 2)})
        if pd.notna(row.get("sma_200")):
            sma200.append({"time": ts, "value": round(row["sma_200"], 2)})

    return {
        "symbol": symbol.upper(),
        "candles": candles,
        "volumes": volumes,
        "sma20": sma20,
        "sma50": sma50,
        "sma200": sma200,
    }


# ===== 组合仪表盘 =====

@app.get("/legacy/dashboard", response_class=HTMLResponse)
def dashboard_page(request: Request, db: Session = Depends(get_db)):
    """组合级仪表盘：资产曲线 + 风险预算 + 月度热力图"""
    from performance import compute_portfolio_performance
    from risk_engine import compute_portfolio_risk

    perf = compute_portfolio_performance(db)
    risk = compute_portfolio_risk(db)
    goals = db.query(UserGoals).first()
    positions = db.query(Position).filter(Position.is_open == True).all()
    regime = detect_market_regime()

    # 行业分布
    sector_exposure = {}
    for p in positions:
        m = p.market or "unknown"
        sector_exposure[m] = sector_exposure.get(m, 0) + (p.risk_pct_of_account or 0)

    # Paper orders
    from broker import get_paper_orders
    recent_orders = get_paper_orders()[:10]

    # Scheduler status
    from scheduler import get_scheduler_status
    scheduler_status = get_scheduler_status()

    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "perf": perf,
        "risk": risk,
        "goals": goals,
        "positions": positions,
        "regime": regime,
        "sector_exposure": sector_exposure,
        "recent_orders": recent_orders,
        "scheduler": scheduler_status,
    })


# ===== Paper Trading 订单 API =====

@app.post("/api/paper-order", response_class=HTMLResponse)
def paper_order(
    request: Request,
    symbol: str = Form(...),
    qty: int = Form(...),
    side: str = Form("buy"),
    order_type: str = Form("market"),
    db: Session = Depends(get_db),
):
    """提交 Paper Trading 订单"""
    from broker import submit_order as broker_submit
    result = broker_submit(symbol=symbol.upper(), qty=qty, side=side, order_type=order_type, paper=True)
    if "error" in result:
        return HTMLResponse(f'<div class="text-accent-red text-sm p-2">{result["error"]}</div>')
    return HTMLResponse(
        f'<div class="text-accent-green text-sm p-2">Paper 订单成交: '
        f'{result["side"].upper()} {result["quantity"]} {result["symbol"]} @ ${result["fill_price"]}'
        f'<span class="text-gray-500 ml-2">(ID: {result["order_id"]})</span></div>'
    )


# ===== Scheduler Status =====

@app.get("/api/scheduler")
def scheduler_status():
    from scheduler import get_scheduler_status
    return get_scheduler_status()


# ===== Backtest API (JSON) =====

def _metrics_to_dict(m) -> dict:
    """Convert BacktestMetrics dataclass to JSON-safe dict."""
    return {
        "total_return": m.total_return,
        "annual_return": m.annual_return,
        "max_drawdown": m.max_drawdown,
        "sharpe_ratio": m.sharpe_ratio,
        "sortino_ratio": m.sortino_ratio,
        "win_rate": m.win_rate,
        "total_trades": m.total_trades,
        "profit_factor": m.profit_factor,
        "avg_win": m.avg_win,
        "avg_loss": m.avg_loss,
        "final_equity": m.final_equity,
        "max_consecutive_losses": m.max_consecutive_losses,
        "avg_holding_days": m.avg_holding_days,
    }


@app.post("/api/backtest/run")
def api_backtest_run(payload: dict, db: Session = Depends(get_db)):
    """
    运行完整回测并返回详细 JSON 结果（含每日明细）。
    """
    import json as _json
    from backtester import run_full_backtest

    strategy_name = payload.get("strategy_name")
    symbol = payload.get("symbol", "SPY")
    start_date = payload.get("start_date")
    end_date = payload.get("end_date")
    cost_model = payload.get("cost_model", "default")

    if not strategy_name:
        return JSONResponse({"error": "strategy_name is required"}, status_code=400)

    # 默认日期：5 年前到今天
    if not start_date:
        from datetime import timedelta
        start_date = (datetime.now() - timedelta(days=5 * 365)).strftime("%Y-%m-%d")
    if not end_date:
        end_date = datetime.now().strftime("%Y-%m-%d")

    # Find or create StrategyConfig
    config = db.query(StrategyConfig).filter(
        StrategyConfig.strategy_name == strategy_name,
        StrategyConfig.symbol == symbol,
    ).first()
    if not config:
        config = StrategyConfig(
            strategy_name=strategy_name,
            symbol=symbol,
            symbol_pool=symbol,
        )
        db.add(config)
        db.commit()
        db.refresh(config)

    goals = db.query(UserGoals).first()
    result = run_full_backtest(
        config, goals, db,
        cost_model_name=cost_model,
        start_date=start_date,
        end_date=end_date,
        collect_daily=True,
    )

    if "error" in result:
        return JSONResponse({"error": result["error"]}, status_code=400)

    metrics = result["metrics"]
    report = result["report"]
    wf = result["walk_forward"]

    # Warnings
    warnings = []
    try:
        from datetime import timedelta
        d0 = datetime.strptime(start_date, "%Y-%m-%d")
        d1 = datetime.strptime(end_date, "%Y-%m-%d")
        if (d1 - d0).days < 365:
            warnings.append("数据量不足1年，统计结果参考价值有限。建议至少3年。")
    except Exception:
        pass

    return {
        "metrics": _metrics_to_dict(metrics),
        "trades": (metrics.trades or [])[:100],
        "daily_details": metrics.daily_details or [],
        "monthly_returns": report.get("monthly_returns", []),
        "walk_forward": {
            "in_sample": _metrics_to_dict(wf["in_sample"]),
            "out_of_sample": _metrics_to_dict(wf["out_of_sample"]),
            "overfit_ratio": wf["overfit_ratio"],
        },
        "compatible": result["compatible"],
        "warnings": warnings,
    }


@app.get("/api/backtest/daily/{run_id}")
def api_backtest_daily(run_id: int, db: Session = Depends(get_db)):
    """
    返回已存储回测运行的每日明细。
    """
    import json as _json
    from backtester import run_full_backtest

    run = db.query(BacktestRun).filter(BacktestRun.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Backtest run not found")

    config = db.query(StrategyConfig).filter(StrategyConfig.id == run.strategy_config_id).first()
    if not config:
        raise HTTPException(status_code=404, detail="Strategy config not found")

    # Re-run with collect_daily=True for the stored date range
    goals = db.query(UserGoals).first()
    result = run_full_backtest(
        config, goals, db=None,
        start_date=run.start_date,
        end_date=run.end_date,
        collect_daily=True,
    )

    if "error" in result:
        return JSONResponse({"error": result["error"]}, status_code=400)

    metrics = result["metrics"]
    return {
        "run_id": run_id,
        "start_date": run.start_date,
        "end_date": run.end_date,
        "daily_details": metrics.daily_details or [],
    }


# ============================================================
# QuantPrism v4 — 7-page architecture routes
# ============================================================

# ===== Page 1: 设定目标 =====

@app.get("/goals", response_class=HTMLResponse)
def goals_page(request: Request, db: Session = Depends(get_db)):
    goals = db.query(UserGoals).order_by(UserGoals.updated_at.desc()).first()
    constraints = None
    asset_classes_list = _parse_asset_classes(goals.asset_classes if goals else "")
    if goals:
        constraints = derive_constraints(goals.max_drawdown, goals.risk_per_trade)
    return templates.TemplateResponse("qp_goals.html", {
        "request": request,
        "goals": goals,
        "constraints": constraints,
        "asset_classes_list": asset_classes_list,
    })


@app.post("/goals/save", response_class=HTMLResponse)
def save_goals_v4(
    request: Request,
    annual_return_target: float = Form(...),
    max_drawdown: float = Form(...),
    risk_per_trade: float = Form(2.0),
    asset_classes: str = Form(""),
    holding_period: str = Form("days_weeks"),
    assets: list[str] = Form([]),
    horizon: str = Form(""),
    redirect_to: str = Form(""),
    db: Session = Depends(get_db),
):
    normalized_asset_classes = _normalize_goal_assets(asset_classes, assets)
    normalized_holding_period = _normalize_holding_period(holding_period, horizon)
    goals = db.query(UserGoals).first()
    if goals:
        goals.annual_return_target = annual_return_target / 100
        goals.max_drawdown = max_drawdown / 100
        goals.risk_per_trade = risk_per_trade / 100
        goals.asset_classes = normalized_asset_classes
        goals.holding_period = normalized_holding_period
    else:
        goals = UserGoals(
            annual_return_target=annual_return_target / 100,
            max_drawdown=max_drawdown / 100,
            risk_per_trade=risk_per_trade / 100,
            asset_classes=normalized_asset_classes,
            holding_period=normalized_holding_period,
        )
        db.add(goals)

    constraints = derive_constraints(goals.max_drawdown, goals.risk_per_trade)
    goals.max_positions = constraints.max_positions
    goals.max_position_pct = constraints.max_position_pct
    db.commit()

    if redirect_to == "hunt":
        return RedirectResponse("/hunt", status_code=303)

    return templates.TemplateResponse("partials/goals_display.html", {
        "request": request,
        "goals": goals,
        "constraints": constraints,
        "saved": True,
    })


# ===== Page 2: 策略猎手 =====

@app.get("/hunt", response_class=HTMLResponse)
def hunt_page(request: Request, db: Session = Depends(get_db)):
    goals = db.query(UserGoals).order_by(UserGoals.updated_at.desc()).first()
    # Pre-load library strategies for initial display
    library = get_strategy_library()
    strategies = []
    if goals:
        goals_dict = {
            "annual_return": goals.annual_return_target,
            "max_drawdown": goals.max_drawdown,
            "holding_period": goals.holding_period or "days_weeks",
        }
        for s in library:
            score = compute_match_score(s, goals_dict)
            strategies.append({**s, "match_pct": round(score)})
        strategies.sort(key=lambda x: x["match_pct"], reverse=True)
        strategies = strategies[:10]  # Top 10
    else:
        strategies = library[:10]
        for s in strategies:
            s["match_pct"] = 50  # Default if no goals

    return templates.TemplateResponse("qp_hunt.html", {
        "request": request,
        "goals": goals,
        "strategies": strategies,
    })


@app.post("/hunt/search", response_class=HTMLResponse)
def hunt_search(request: Request, db: Session = Depends(get_db)):
    """Search GitHub + AI for strategies matching goals"""
    goals = db.query(UserGoals).order_by(UserGoals.updated_at.desc()).first()
    if not goals:
        return HTMLResponse('<div class="text-center text-gray-400 py-8">请先设定投资目标</div>')

    goals_dict = {
        "annual_return": goals.annual_return_target,
        "max_drawdown": goals.max_drawdown,
        "holding_period": goals.holding_period or "days_weeks",
    }

    # Search library
    library = get_strategy_library()
    results = []
    for s in library:
        score = compute_match_score(s, goals_dict)
        results.append({**s, "match_pct": round(score), "source": s.get("source", "library")})

    # Try GitHub search (non-blocking, catch errors)
    try:
        gh_results = search_github_strategies(
            f"trading strategy {goals.holding_period or 'swing'} python",
            max_results=3,
        )
        for r in gh_results:
            score = compute_match_score(r, goals_dict)
            results.append({**r, "match_pct": round(score), "source": "github"})
    except Exception:
        pass

    results.sort(key=lambda x: x["match_pct"], reverse=True)

    return templates.TemplateResponse("partials/hunt_results.html", {
        "request": request,
        "strategies": results[:15],
        "goals": goals,
    })


@app.post("/hunt/ai-generate", response_class=HTMLResponse)
def hunt_ai_generate(request: Request, db: Session = Depends(get_db)):
    """Ask AI to generate a new strategy"""
    goals = db.query(UserGoals).order_by(UserGoals.updated_at.desc()).first()
    if not goals:
        return HTMLResponse('<div class="text-center text-gray-400 py-4">请先设定投资目标</div>')

    goals_dict = {
        "annual_return": goals.annual_return_target,
        "max_drawdown": goals.max_drawdown,
        "holding_period": goals.holding_period or "days_weeks",
        "asset_classes": goals.asset_classes or "us_stocks,etf",
    }

    try:
        strategy = ai_generate_strategy(goals_dict)
        if strategy:
            score = compute_match_score(strategy, goals_dict)
            strategy["match_pct"] = round(score)
            strategy["source"] = "ai"
            return templates.TemplateResponse("partials/hunt_results.html", {
                "request": request,
                "strategies": [strategy],
                "goals": goals,
            })
    except Exception:
        pass

    return HTMLResponse('<div class="text-center text-gray-400 py-4">AI 暂时无法生成策略，请稍后再试</div>')


# ===== Page 3: 回测实验室 =====

@app.get("/backtest", response_class=HTMLResponse)
def backtest_page(request: Request, strategy: str = "", symbol: str = "", db: Session = Depends(get_db)):
    goals = db.query(UserGoals).order_by(UserGoals.updated_at.desc()).first()
    configs = db.query(StrategyConfig).all()
    # Sort: put strategies that actually trade (sma, rsi, bollinger) first
    trade_strats = ["sma_crossover", "rsi_momentum", "bollinger_reversion"]
    configs.sort(key=lambda c: (0 if c.strategy_name in trade_strats else 1, c.strategy_name))
    strategy_names = [c.display_name or c.strategy_name for c in configs]
    if not strategy_names:
        from strategies import get_all_strategies
        strategy_names = sorted(get_all_strategies().keys())

    five_years_ago = (datetime.now() - timedelta(days=5*365)).strftime('%Y-%m-%d')
    today = datetime.now().strftime('%Y-%m-%d')

    return templates.TemplateResponse("qp_backtest.html", {
        "request": request,
        "goals": goals,
        "strategies": strategy_names,
        "configs": configs,
        "preselect_strategy": strategy,
        "preselect_symbol": symbol or "SPY",
        "five_years_ago": five_years_ago,
        "today": today,
    })


@app.post("/backtest/run", response_class=HTMLResponse)
def backtest_run(
    request: Request,
    strategy_id: int = Form(0),
    strategy_name: str = Form(""),
    symbol: str = Form("SPY"),
    start_date: str = Form("2006-01-01"),
    end_date: str = Form(""),
    db: Session = Depends(get_db),
):
    import json as _json
    from backtester import run_full_backtest

    goals = db.query(UserGoals).order_by(UserGoals.updated_at.desc()).first()

    # Find or create a config for this backtest
    config = None
    if strategy_id:
        config = db.query(StrategyConfig).filter(StrategyConfig.id == strategy_id).first()
    if not config and strategy_name:
        config = db.query(StrategyConfig).filter(StrategyConfig.strategy_name == strategy_name).first()
    if not config:
        # Use first active config or create a temp one
        config = db.query(StrategyConfig).filter(StrategyConfig.is_active == True).first()

    if not config:
        return HTMLResponse('<div class="text-center text-red-400 py-8">未找到策略配置，请先在策略猎手中选择策略</div>')

    # Override symbol
    original_pool = config.symbol_pool
    config.symbol_pool = symbol

    if not end_date:
        end_date = datetime.now().strftime('%Y-%m-%d')

    result = run_full_backtest(config, goals, db=None, start_date=start_date, end_date=end_date, collect_daily=True)
    config.symbol_pool = original_pool  # restore

    if "error" in result:
        return HTMLResponse(f'<div class="text-center text-red-400 py-8">回测失败: {result["error"]}</div>')

    metrics = result["metrics"]

    # Prepare chart data
    chart_data = []
    heatmap_data = []

    if hasattr(metrics, "daily_details") and metrics.daily_details:
        for d in metrics.daily_details:
            if "date" in d:
                chart_data.append({
                    "time": d["date"],
                    "open": round(d.get("open", d.get("close", 0)), 2),
                    "high": round(d.get("high", d.get("close", 0)), 2),
                    "low": round(d.get("low", d.get("close", 0)), 2),
                    "close": round(d.get("close", 0), 2),
                    "volume": d.get("volume", 0),
                })

    # Compute monthly returns from daily_details (use close price for heatmap)
    if hasattr(metrics, "daily_details") and metrics.daily_details:
        monthly = {}
        for d in metrics.daily_details:
            dt = d.get("date", "")
            equity = d.get("equity", 0)
            # Always use equity curve for monthly returns (avoids price/equity discontinuity)
            val = equity
            if len(dt) >= 7 and val:
                ym = dt[:7]  # YYYY-MM
                if ym not in monthly:
                    monthly[ym] = {"start": val, "end": val}
                monthly[ym]["end"] = val

        for ym, vals in sorted(monthly.items()):
            parts = ym.split("-")
            if len(parts) == 2:
                y, m = int(parts[0]), int(parts[1])
                ret = ((vals["end"] / vals["start"]) - 1) * 100 if vals["start"] else 0
                heatmap_data.append([m - 1, y, round(ret, 1)])

    # Trade markers for chart
    trades_markers = []
    if hasattr(metrics, "trades") and metrics.trades:
        for t in metrics.trades:
            if "entry_date" in t:
                trades_markers.append({"time": t["entry_date"], "type": "buy", "price": t.get("entry_price", 0)})
            if "exit_date" in t:
                trades_markers.append({"time": t["exit_date"], "type": "sell", "price": t.get("exit_price", 0)})

    return templates.TemplateResponse("partials/backtest_inline.html", {
        "request": request,
        "metrics": {
            "total_return": round(metrics.total_return, 4) if hasattr(metrics, "total_return") else 0,
            "annual_return": round(metrics.annual_return, 4) if hasattr(metrics, "annual_return") else 0,
            "max_drawdown": round(metrics.max_drawdown, 4) if hasattr(metrics, "max_drawdown") else 0,
            "sharpe_ratio": round(metrics.sharpe_ratio, 2) if hasattr(metrics, "sharpe_ratio") else 0,
            "win_rate": round(metrics.win_rate, 4) if hasattr(metrics, "win_rate") else 0,
            "profit_factor": round(metrics.profit_factor, 2) if hasattr(metrics, "profit_factor") else 0,
            "total_trades": metrics.total_trades if hasattr(metrics, "total_trades") else 0,
            "avg_hold_days": round(metrics.avg_hold_days, 1) if hasattr(metrics, "avg_hold_days") else 0,
            "max_consecutive_losses": metrics.max_consecutive_losses if hasattr(metrics, "max_consecutive_losses") else 0,
        },
        "goals": goals,
        "symbol": symbol,
        "chart_data": _json.dumps(chart_data),
        "heatmap_data": _json.dumps(heatmap_data),
        "trades_markers": _json.dumps(trades_markers),
    })


# ===== Page 4: 标的扫描 =====

@app.get("/scan", response_class=HTMLResponse)
def scan_page(request: Request, db: Session = Depends(get_db)):
    goals = db.query(UserGoals).order_by(UserGoals.updated_at.desc()).first()
    configs = db.query(StrategyConfig).filter(StrategyConfig.is_active == True).all()
    strategy_names = [c.display_name or c.strategy_name for c in configs]
    return templates.TemplateResponse("qp_scan.html", {
        "request": request,
        "goals": goals,
        "strategies": strategy_names,
        "configs": configs,
    })


@app.post("/scan/run", response_class=HTMLResponse)
async def scan_run(
    request: Request,
    db: Session = Depends(get_db),
):
    form = await request.form()
    strategy_name = form.get("strategy_name", "sma_crossover")
    scan_ranges = form.getlist("scan_range")  # checkboxes: stocks, etf, options
    if not scan_ranges:
        scan_ranges = ["stocks", "etf"]

    goals = db.query(UserGoals).order_by(UserGoals.updated_at.desc()).first()

    # Map checkbox values to index names
    index_name = "all"  # default: scan everything
    if "stocks" in scan_ranges and "etf" not in scan_ranges:
        index_name = "sp500"
    elif "etf" in scan_ranges and "stocks" not in scan_ranges:
        index_name = "nasdaq100"  # ETFs are in nasdaq100 top

    # Find the config for this strategy
    config = db.query(StrategyConfig).filter(
        StrategyConfig.strategy_name == strategy_name,
        StrategyConfig.is_active == True,
    ).first()

    import yaml
    params = yaml.safe_load(config.params_yaml) if config and config.params_yaml else {}

    try:
        result = scan_index(index_name, strategy_name, params)
        matches = result.get("matches", [])
    except Exception as e:
        return HTMLResponse(f'<div class="text-center text-red-400 py-8">扫描失败: {str(e)}</div>')

    # Map scanner results to template fields
    results = []
    account_balance = 15000
    for m in matches[:20]:
        symbol = m.get("symbol", "")
        price = m.get("current_price", 0)
        stop_loss = m.get("stop_loss", price * 0.95)
        target = m.get("target_price", price * 1.10)
        risk_reward = m.get("risk_reward", 0)
        suggested_pct = m.get("suggested_position_pct", 5.0)
        position_amount = account_balance * suggested_pct / 100
        max_loss = position_amount * (abs(price - stop_loss) / price) if price else 0

        # Build signal reason from available data
        rsi = m.get("rsi", 50)
        atr_pct = m.get("atr_pct", 0)
        days_since = m.get("days_since_signal", 0)
        signal_date = m.get("signal_date", "")
        reason = f"策略 {m.get('strategy_name', '')} 在 {signal_date} 发出买入信号"
        if rsi:
            reason += f"，RSI {rsi}"
        if days_since == 0:
            reason += "（今日信号）"
        elif days_since <= 1:
            reason += "（昨日信号）"

        results.append({
            "symbol": symbol,
            "company_name": symbol,
            "signal_type": "buy" if m.get("signal_direction") == "long" else m.get("signal_direction", "buy"),
            "signal_reason": reason,
            "price": round(price, 2),
            "change_pct": round(atr_pct, 2),
            "entry_low": round(m.get("entry_zone", price * 0.995), 2),
            "entry_high": round(price, 2),
            "stop_loss": round(stop_loss, 2),
            "stop_loss_pct": round((stop_loss / price - 1) * 100, 1) if price else 0,
            "target": round(target, 2),
            "target_pct": round((target / price - 1) * 100, 1) if price else 0,
            "risk_reward": risk_reward,
            "position_pct": suggested_pct,
            "position_amount": round(position_amount, 0),
            "max_loss": round(max_loss, 0),
            "max_loss_pct": round(max_loss / account_balance * 100, 2) if account_balance else 0,
        })

    return templates.TemplateResponse("partials/scan_results.html", {
        "request": request,
        "results": results,
        "scan_count": result.get("symbols_scanned", 0),
        "scan_time": result.get("scan_time_sec", 0),
    })


@app.post("/scan/paper-order", response_class=HTMLResponse)
def scan_paper_order(
    request: Request,
    symbol: str = Form(...),
    price: float = Form(0),
    quantity: float = Form(0),
    entry_low: float = Form(0),
    entry_high: float = Form(0),
    stop_loss: float = Form(0),
    target: float = Form(0),
    position_pct: float = Form(0),
    db: Session = Depends(get_db),
):
    signal_price = price or entry_high or entry_low or target or 0
    signal_quantity = quantity or max(int(round(position_pct)) or 1, 1)
    signal = TradeSignal(
        symbol=symbol,
        direction="long",
        signal_price=signal_price,
        signal_stop_loss=stop_loss or None,
        signal_take_profit=target or None,
        signal_quantity=signal_quantity,
        status="pending",
    )
    db.add(signal)
    db.commit()
    return HTMLResponse(
        f'<span class="text-accent-green text-sm">✅ 已模拟下单: 买入 {symbol} {signal_quantity}股 @${signal_price}</span>'
    )


# ===== Page 5: 风控护盾 (v4 rewrite) =====

@app.get("/risk", response_class=HTMLResponse)
def risk_page_v4(request: Request, db: Session = Depends(get_db)):
    from risk_engine import compute_portfolio_risk
    goals = db.query(UserGoals).order_by(UserGoals.updated_at.desc()).first()
    positions = db.query(Position).filter(Position.is_open == True).all()
    risk_data = compute_portfolio_risk(db)
    alert_config = db.query(AlertConfig).first()

    # Derive rating
    headroom = risk_data.get("drawdown_headroom", 1)
    if headroom > 0.05:
        rating = "safe"
        rating_color = "green"
    elif headroom > 0.02:
        rating = "caution"
        rating_color = "yellow"
    else:
        rating = "danger"
        rating_color = "red"

    risk_data["rating"] = rating
    risk_data["rating_color"] = rating_color
    risk_data["headroom"] = round(headroom * 100, 1)

    # Build rules list
    rules = [
        {
            "id": "max_loss_per_trade",
            "label": "单笔最大亏损",
            "value": round((goals.risk_per_trade if goals else 0.02) * 100, 0),
            "unit": "%",
            "description": "每笔交易最多亏账户的这个比例",
            "status": "safe",
        },
        {
            "id": "max_drawdown",
            "label": "总回撤上限",
            "value": round((goals.max_drawdown if goals else 0.10) * 100, 0),
            "unit": "%",
            "description": f"当前 -{round(risk_data.get('current_drawdown', 0) * 100, 1)}%",
            "status": "safe" if risk_data.get("current_drawdown", 0) < (goals.max_drawdown if goals else 0.10) else "warning",
        },
        {
            "id": "max_positions",
            "label": "最大持仓数",
            "value": goals.max_positions if goals and goals.max_positions else 5,
            "unit": "个",
            "description": f"当前 {len(positions)} 个",
                "status": "safe" if len(positions) <= ((goals.max_positions if goals and goals.max_positions else 5)) else "warning",
            },
        {
            "id": "sector_limit",
            "label": "单行业上限",
            "value": 40,
            "unit": "%",
            "description": "防止单一行业过度集中",
            "status": "safe",
        },
        {
            "id": "vix_threshold",
            "label": "危机暂停: VIX >",
            "value": round(alert_config.vix_spike_threshold if alert_config else 30, 0),
            "unit": "",
            "description": f"当前 VIX {round(risk_data.get('vix', 0), 1)}",
            "status": "safe" if risk_data.get("vix", 0) < (alert_config.vix_spike_threshold if alert_config else 30) else "warning",
        },
    ]

    # AI suggestions (static defaults, can be enhanced later)
    ai_suggestions = [
        {
            "title": "对冲建议",
            "description": "买入 SPY Put 对冲下行风险，花小钱买保险",
            "action_label": "执行对冲",
        },
        {
            "title": "保留现金",
            "description": "建议维持 ≥ 20% 现金，留够子弹应对好机会",
            "action_label": None,
        },
    ]

    return templates.TemplateResponse("qp_risk.html", {
        "request": request,
        "risk_data": risk_data,
        "rules": rules,
        "goals": goals,
        "positions": positions,
        "ai_suggestions": ai_suggestions,
    })


@app.post("/risk/rules", response_class=HTMLResponse)
def save_risk_rules(
    request: Request,
    rule_id: str = Form(""),
    value: float = Form(0),
    db: Session = Depends(get_db),
):
    goals = db.query(UserGoals).first()
    alert_config = db.query(AlertConfig).first()

    if rule_id == "max_loss_per_trade" and goals:
        goals.risk_per_trade = value / 100
    elif rule_id == "max_drawdown" and goals:
        goals.max_drawdown = value / 100
    elif rule_id == "max_positions" and goals:
        goals.max_positions = int(value)
    elif rule_id == "vix_threshold" and alert_config:
        alert_config.vix_spike_threshold = value

    db.commit()
    return HTMLResponse('<span class="text-accent-green text-sm">✅ 已保存</span>')


# ===== Page 6: 观察列表 =====

@app.get("/watchlist", response_class=HTMLResponse)
def watchlist_page(request: Request, db: Session = Depends(get_db)):
    items_db = db.query(WatchlistItem).order_by(WatchlistItem.created_at.desc()).all()
    items = []
    for item in items_db:
        price = 0
        change_pct = 0
        try:
            data = fetch_current_price(item.symbol)
            if isinstance(data, dict):
                price = data.get("price", 0)
                change_pct = data.get("change_pct", 0) * 100
            else:
                price = float(data)
        except Exception:
            pass
        items.append({
            "id": item.id,
            "symbol": item.symbol,
            "price": round(price, 2) if price else 0,
            "change_pct": round(change_pct, 2),
            "added_date": item.created_at.strftime("%m/%d") if item.created_at else "",
            "added_from": item.added_from or "manual",
        })

    return templates.TemplateResponse("qp_watchlist.html", {
        "request": request,
        "items": items,
    })


@app.post("/watchlist/add", response_class=HTMLResponse)
def watchlist_add(
    request: Request,
    symbol: str = Form(...),
    from_source: str = Form(""),
    from_: str = Form("", alias="from"),
    db: Session = Depends(get_db),
):
    existing = db.query(WatchlistItem).filter(WatchlistItem.symbol == symbol.upper()).first()
    if not existing:
        added_from = from_source or from_ or "scanner"
        db.add(WatchlistItem(symbol=symbol.upper(), added_from=added_from))
        db.commit()
    return HTMLResponse(f'<span class="text-accent-green text-sm">✅ {symbol.upper()} 已加入观察列表</span>')


@app.delete("/watchlist/remove/{item_id}", response_class=HTMLResponse)
def watchlist_remove(item_id: int, db: Session = Depends(get_db)):
    item = db.query(WatchlistItem).filter(WatchlistItem.id == item_id).first()
    if item:
        db.delete(item)
        db.commit()
    return HTMLResponse("")


# ===== Page 7: 系统配置 (v4 slim) =====

@app.get("/settings", response_class=HTMLResponse)
def settings_page_v4(request: Request, db: Session = Depends(get_db)):
    api_configs = db.query(ApiConfig).all()
    return templates.TemplateResponse("qp_settings.html", {
        "request": request,
        "api_configs": api_configs,
    })


# ===== v4 Redirects: old routes → new pages =====

@app.get("/dashboard", response_class=RedirectResponse)
def redirect_dashboard():
    return RedirectResponse("/goals", status_code=301)


@app.get("/strategies", response_class=RedirectResponse)
def redirect_strategies():
    return RedirectResponse("/hunt", status_code=301)


@app.get("/strategies/discover", response_class=RedirectResponse)
def redirect_strategies_discover():
    return RedirectResponse("/hunt", status_code=301)


@app.get("/strategies/research", response_class=RedirectResponse)
def redirect_strategies_research():
    return RedirectResponse("/hunt", status_code=301)


@app.get("/strategies/manage", response_class=RedirectResponse)
def redirect_strategies_manage():
    return RedirectResponse("/hunt", status_code=301)


@app.get("/strategies/match", response_class=RedirectResponse)
def redirect_strategies_match():
    return RedirectResponse("/hunt", status_code=301)


@app.get("/strategies/leaderboard", response_class=RedirectResponse)
def redirect_strategies_leaderboard():
    return RedirectResponse("/hunt", status_code=301)


@app.get("/screener", response_class=RedirectResponse)
def redirect_screener():
    return RedirectResponse("/scan", status_code=301)


@app.get("/portfolio", response_class=RedirectResponse)
def redirect_portfolio():
    return RedirectResponse("/risk", status_code=301)


@app.get("/positions", response_class=RedirectResponse)
def redirect_positions():
    return RedirectResponse("/risk", status_code=301)


@app.get("/trade", response_class=RedirectResponse)
def redirect_trade():
    return RedirectResponse("/risk", status_code=301)


@app.get("/execution", response_class=RedirectResponse)
def redirect_execution():
    return RedirectResponse("/risk", status_code=301)


@app.get("/history", response_class=RedirectResponse)
def redirect_history():
    return RedirectResponse("/risk", status_code=301)


@app.get("/performance", response_class=RedirectResponse)
def redirect_performance():
    return RedirectResponse("/risk", status_code=301)


@app.get("/alerts/config", response_class=RedirectResponse)
def redirect_alerts_config():
    return RedirectResponse("/risk", status_code=301)


@app.get("/alerts/history", response_class=RedirectResponse)
def redirect_alerts_history():
    return RedirectResponse("/risk", status_code=301)
# ===========================================================================
# 宏观经济 + 数据层 + 多智能体 路由
# ===========================================================================

@app.get("/macro", response_class=HTMLResponse)
async def macro_page(request: Request):
    """宏观经济仪表板"""
    from data_providers import fetch_macro_data
    macro = fetch_macro_data()
    macro_error = macro.get("error")
    return templates.TemplateResponse("macro.html", {
        "request": request,
        "macro": macro,
        "macro_error": macro_error,
    })


@app.get("/api/fundamentals/{symbol}", response_class=HTMLResponse)
async def api_fundamentals(request: Request, symbol: str):
    """基本面数据卡片 (HTMX partial)"""
    from data_providers import fetch_fundamentals

    symbol = symbol.upper()
    data = fetch_fundamentals(symbol)

    def _fmt_large(v):
        if v is None:
            return "N/A"
        try:
            v = float(v)
            if v >= 1e12:
                return f"${v/1e12:.1f}T"
            elif v >= 1e9:
                return f"${v/1e9:.1f}B"
            elif v >= 1e6:
                return f"${v/1e6:.1f}M"
            return f"${v:,.0f}"
        except Exception:
            return "N/A"

    return templates.TemplateResponse("partials/fundamentals_card.html", {
        "request": request,
        "symbol": symbol,
        "error": data.get("error"),
        "pe_ratio": data.get("pe_ratio"),
        "eps": data.get("eps"),
        "market_cap": data.get("market_cap"),
        "market_cap_fmt": _fmt_large(data.get("market_cap")),
        "dividend_yield": data.get("dividend_yield"),
        "analyst_target": data.get("analyst_target"),
        "analyst_rating": data.get("analyst_rating"),
        "week_52_high": data.get("week_52_high"),
        "week_52_low": data.get("week_52_low"),
        "earnings_date": data.get("earnings_date"),
        "sector": data.get("sector"),
        "industry": data.get("industry"),
        "beta": data.get("beta"),
    })


@app.get("/api/news/{symbol}", response_class=HTMLResponse)
async def api_news(request: Request, symbol: str):
    """新闻面板 (HTMX partial)"""
    from data_providers import fetch_news
    articles = fetch_news(symbol.upper(), limit=10)
    return templates.TemplateResponse("partials/news_panel.html", {
        "request": request,
        "articles": articles,
        "symbol": symbol.upper(),
    })


@app.get("/api/macro-data")
async def api_macro_data():
    """宏观数据 JSON (for Chart.js)"""
    from data_providers import fetch_macro_data
    from fastapi.responses import JSONResponse
    return JSONResponse(fetch_macro_data())


@app.get("/api/rotation", response_class=HTMLResponse)
async def api_rotation(request: Request):
    """板块轮动图 (HTMX partial with Chart.js)"""
    from quant_analysis import compute_relative_rotation
    rotation_data = compute_relative_rotation()
    return templates.TemplateResponse("partials/rotation_chart.html", {
        "request": request,
        "rotation_data": rotation_data,
    })


@app.post("/api/agent-analyze/{symbol}", response_class=HTMLResponse)
async def api_agent_analyze(request: Request, symbol: str):
    """多智能体分析 (4 analysts + debate + verdict)"""
    import dataclasses
    from data_providers import fetch_fundamentals, fetch_news
    from stock_screener import diagnose_stock
    from multi_agent import run_analysis
    from trading_memory import retrieve_similar, store_analysis

    symbol = symbol.upper()

    # Gather context
    diag = diagnose_stock(symbol)
    diag_dict = dataclasses.asdict(diag)
    fundamentals = fetch_fundamentals(symbol)
    news = fetch_news(symbol, limit=10)
    similar = retrieve_similar(symbol, diag_dict)

    # Run multi-agent analysis
    result = run_analysis(symbol, diag_dict, fundamentals, news, similar)

    # Save to memory
    memory_id = store_analysis(symbol, result, diag_dict)
    result["memory_id"] = memory_id if memory_id > 0 else None

    return templates.TemplateResponse("partials/agent_analysis.html", {
        "request": request,
        "error": None,
        "analysts": type("Analysts", (), result.get("analysts", {}))(),
        "bull": result.get("bull", ""),
        "bear": result.get("bear", ""),
        "verdict": result.get("verdict", ""),
        "timestamp": result.get("timestamp", ""),
        "memory_id": result.get("memory_id"),
    })


@app.post("/api/risk-review/{signal_id}", response_class=HTMLResponse)
async def api_risk_review(request: Request, signal_id: int, db: Session = Depends(get_db)):
    """风险审核 (3-way debate)"""
    import dataclasses
    from multi_agent import run_risk_review
    from stock_screener import diagnose_stock

    signal = db.query(TradeSignal).filter(TradeSignal.id == signal_id).first()
    if not signal:
        return HTMLResponse('<div class="text-accent-red text-sm">信号不存在</div>')

    diag = diagnose_stock(signal.symbol)
    diag_dict = dataclasses.asdict(diag)
    signal_dict = {
        "direction": signal.direction,
        "price": signal.signal_price or 0,
        "stop_loss": signal.signal_stop_loss or 0,
    }

    result = run_risk_review(signal.symbol, signal_dict, diag_dict)

    # Return inline HTML for the risk review modal
    html = f"""
    <div class="space-y-4">
        <div class="grid grid-cols-3 gap-3 text-xs">
            <div class="bg-accent-green/10 border border-accent-green/20 rounded-lg p-3">
                <div class="font-semibold text-accent-green mb-2">激进型</div>
                <div class="text-gray-300 whitespace-pre-wrap">{result.get('aggressive','')}</div>
            </div>
            <div class="bg-dark-600 border border-dark-500 rounded-lg p-3">
                <div class="font-semibold text-gray-300 mb-2">中性型</div>
                <div class="text-gray-300 whitespace-pre-wrap">{result.get('neutral','')}</div>
            </div>
            <div class="bg-accent-red/10 border border-accent-red/20 rounded-lg p-3">
                <div class="font-semibold text-accent-red mb-2">保守型</div>
                <div class="text-gray-300 whitespace-pre-wrap">{result.get('conservative','')}</div>
            </div>
        </div>
        <div class="bg-accent-yellow/10 border border-accent-yellow/30 rounded-lg p-4">
            <div class="text-xs font-semibold text-accent-yellow mb-2">⚖️ 风险裁决</div>
            <div class="text-sm text-gray-200 whitespace-pre-wrap">{result.get('verdict','')}</div>
        </div>
    </div>
    """
    return HTMLResponse(html)


@app.post("/api/memory/reflect/{position_id}")
async def api_memory_reflect(position_id: int, db: Session = Depends(get_db)):
    """触发反思（仓位关闭后调用）"""
    from trading_memory import reflect_on_trade
    from fastapi.responses import JSONResponse
    result = reflect_on_trade(position_id)
    return JSONResponse(result)


@app.get("/api/memory/similar/{symbol}")
async def api_memory_similar(symbol: str):
    """获取相似历史分析（BM25 检索）"""
    import dataclasses
    from fastapi.responses import JSONResponse
    from stock_screener import diagnose_stock
    from trading_memory import retrieve_similar

    diag = diagnose_stock(symbol.upper())
    similar = retrieve_similar(symbol.upper(), dataclasses.asdict(diag))
    return JSONResponse(similar)


@app.get("/api/calendar/earnings")
async def api_calendar_earnings(db: Session = Depends(get_db)):
    """获取观察列表中标的的财报日期"""
    from fastapi.responses import JSONResponse
    from data_providers import fetch_earnings_calendar
    from models import WatchlistItem

    symbols = [w.symbol for w in db.query(WatchlistItem).all()]
    if not symbols:
        symbols = ["AAPL", "MSFT", "NVDA", "GOOGL", "META"]  # defaults

    return JSONResponse(fetch_earnings_calendar(symbols))