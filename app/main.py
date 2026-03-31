"""
Goal-Driven Trading OS — FastAPI Application
Phase 1: 目标设定 + 仓位计算器 + 手动持仓 + 交易日志
"""
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, Depends, Request, Form, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from models import (init_db, get_db, UserGoals, Position, TradeJournal, JournalCompliance,
                     StrategyConfig, BacktestRun, TradeSignal, StrategyLeaderboard,
                     AlertConfig, AlertHistory, ExecutionLog, ApiConfig, Base, engine)
from calculator import calculate_position_size, derive_constraints, check_can_open_position
from schemas import GoalsCreate, PositionCreate, CalculateRequest, PositionClose
from market_data import fetch_current_price, fetch_vix, detect_market_regime, fetch_stock_history, compute_technicals
from sync import sync_positions_from_broker
from stock_screener import SECTORS, diagnose_stock, screen_sector, build_combo
from ibkr_options import fetch_ibkr_options_chain, filter_options_for_sell_put

app = FastAPI(title="Goal-Driven Trading OS", version="0.1.0")

BASE_DIR = Path(__file__).resolve().parent
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


@app.on_event("startup")
def startup():
    init_db()
    # 确保 JournalCompliance 有一条记录
    db = next(get_db())
    if not db.query(JournalCompliance).first():
        db.add(JournalCompliance())
        db.commit()
    db.close()


# ===== 页面路由 =====

# ===== 交易机会 (首页) =====

@app.get("/", response_class=HTMLResponse)
def opportunities_page(request: Request, sector: str = "TECH", db: Session = Depends(get_db)):
    """交易机会：板块筛选 + AI 诊断 + 期权链"""
    goals = db.query(UserGoals).first()
    regime = detect_market_regime()
    return templates.TemplateResponse("opportunities.html", {
        "request": request,
        "sectors": SECTORS,
        "current_sector": sector,
        "goals": goals,
        "regime": regime,
    })


# ===== 我的持仓 =====

@app.get("/positions", response_class=HTMLResponse)
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
    risk_per_trade: float = Form(0.02),
    db: Session = Depends(get_db),
):
    # 表单输入是百分比 (如 15), 模型存小数 (如 0.15)
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
        goals.updated_at = datetime.utcnow()
    else:
        goals = UserGoals(
            annual_return_target=goals_data.annual_return_target,
            max_drawdown=goals_data.max_drawdown,
            risk_per_trade=goals_data.risk_per_trade,
            max_positions=constraints.max_positions,
            max_position_pct=constraints.max_position_pct,
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

    # 返回更新后的持仓列表
    positions = db.query(Position).filter(Position.is_open == True).all()
    total_risk_pct = sum(p.risk_pct_of_account or 0 for p in positions)

    return templates.TemplateResponse("partials/positions_list.html", {
        "request": request,
        "positions": positions,
        "total_risk_pct": total_risk_pct,
    })


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

    positions = db.query(Position).filter(Position.is_open == True).all()
    total_risk_pct = sum(p.risk_pct_of_account or 0 for p in positions)

    return templates.TemplateResponse("partials/positions_list.html", {
        "request": request,
        "positions": positions,
        "total_risk_pct": total_risk_pct,
    })


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
    positions = db.query(Position).filter(Position.is_open == True).all()
    total_risk_pct = sum(p.risk_pct_of_account or 0 for p in positions)
    return templates.TemplateResponse("partials/positions_list.html", {
        "request": request,
        "positions": positions,
        "total_risk_pct": total_risk_pct,
        "sync_result": result,
    })


@app.get("/api/prices/{symbol}")
def get_price(symbol: str):
    return fetch_current_price(symbol)


@app.get("/api/vix")
def get_vix():
    return fetch_vix()


@app.get("/api/regime")
def get_regime():
    return detect_market_regime()


# ===== Phase 2: Strategies (will be populated next) =====

@app.get("/strategies", response_class=HTMLResponse)
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
def run_backtest_endpoint(request: Request, config_id: int, db: Session = Depends(get_db)):
    config = db.query(StrategyConfig).filter(StrategyConfig.id == config_id).first()
    if not config:
        raise HTTPException(status_code=404, detail="Strategy config not found")

    from backtester import run_full_backtest
    goals = db.query(UserGoals).first()
    result = run_full_backtest(config, goals, db)

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


@app.get("/strategies/match", response_class=HTMLResponse)
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


@app.get("/strategies/leaderboard", response_class=HTMLResponse)
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


# ===== 标的筛选 + AI 诊断 + 组合推荐 + 期权链 =====

@app.get("/screener", response_class=HTMLResponse)
def screener_page(request: Request, sector: str = "TECH", db: Session = Depends(get_db)):
    goals = db.query(UserGoals).first()
    regime = detect_market_regime()
    return templates.TemplateResponse("screener.html", {
        "request": request,
        "sectors": SECTORS,
        "current_sector": sector,
        "goals": goals,
        "regime": regime,
    })


@app.post("/screener/scan", response_class=HTMLResponse)
def scan_sector(request: Request, sector: str = Form("TECH"), db: Session = Depends(get_db)):
    goals = db.query(UserGoals).first()

    # Use multi-strategy opportunity engine if goals set
    from opportunity_engine import find_opportunities
    account_balance = 100000
    if goals:
        from broker import fetch_account_info
        acct = fetch_account_info()
        if "equity" in acct:
            account_balance = acct["equity"]

    opps = find_opportunities(
        goals_return=goals.annual_return_target if goals else 0.15,
        goals_drawdown=goals.max_drawdown if goals else 0.10,
        risk_per_trade=goals.risk_per_trade if goals else 0.02,
        account_balance=account_balance,
        sectors=[sector],
    )

    # Also get stock diagnostics for the table
    results = screen_sector(sector)

    return templates.TemplateResponse("partials/screener_results.html", {
        "request": request,
        "results": results,
        "opportunities": opps.get("opportunities", [])[:15],
        "combos": opps.get("combos", [])[:3],
        "total_strategies": opps.get("total_strategies", 0),
        "total_compatible": opps.get("total_compatible", 0),
        "sector_name": SECTORS.get(sector, {}).get("name", sector),
    })


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

@app.get("/portfolio", response_class=HTMLResponse)
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

@app.get("/trade", response_class=HTMLResponse)
def trade_page(request: Request, db: Session = Depends(get_db)):
    pending = db.query(TradeSignal).filter(TradeSignal.status == "pending").all()
    confirmed = db.query(TradeSignal).filter(TradeSignal.status == "confirmed").all()
    recent_executed = db.query(TradeSignal).filter(TradeSignal.status == "executed").order_by(TradeSignal.execution_time.desc()).limit(10).all()
    goals = db.query(UserGoals).first()
    recent_journals = db.query(TradeJournal).order_by(TradeJournal.created_at.desc()).limit(5).all()
    return templates.TemplateResponse("trade.html", {
        "request": request,
        "pending": pending,
        "confirmed": confirmed,
        "recent_executed": recent_executed,
        "goals": goals,
        "recent_journals": recent_journals,
    })

# Keep /execution as alias
@app.get("/execution", response_class=HTMLResponse)
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

@app.get("/history", response_class=HTMLResponse)
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
@app.get("/performance", response_class=HTMLResponse)
def performance_page(request: Request, db: Session = Depends(get_db)):
    return history_page(request, db)


# ===== Phase 5: Risk + Alerts =====

@app.get("/risk", response_class=HTMLResponse)
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


@app.get("/alerts/config", response_class=HTMLResponse)
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


@app.get("/alerts/history", response_class=HTMLResponse)
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
]


@app.get("/settings", response_class=HTMLResponse)
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
