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
                     AlertConfig, AlertHistory, ExecutionLog, Base, engine)
from calculator import calculate_position_size, derive_constraints, check_can_open_position
from schemas import GoalsCreate, PositionCreate, CalculateRequest, PositionClose
from market_data import fetch_current_price, fetch_vix, detect_market_regime, fetch_stock_history, compute_technicals
from sync import sync_positions_from_broker

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

@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_db)):
    goals = db.query(UserGoals).order_by(UserGoals.updated_at.desc()).first()
    positions = db.query(Position).filter(Position.is_open == True).all()
    closed = db.query(Position).filter(Position.is_open == False).order_by(Position.close_date.desc()).limit(10).all()
    compliance = db.query(JournalCompliance).first()
    recent_journals = db.query(TradeJournal).order_by(TradeJournal.created_at.desc()).limit(5).all()

    constraints = None
    if goals:
        constraints = derive_constraints(goals.max_drawdown, goals.risk_per_trade)

    total_risk_pct = sum(p.risk_pct_of_account or 0 for p in positions)

    show_journal_reminder = False
    if compliance and compliance.trades_without_journal >= 3:
        show_journal_reminder = True

    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "goals": goals,
        "constraints": constraints,
        "positions": positions,
        "closed_positions": closed,
        "total_risk_pct": total_risk_pct,
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
    result = sync_positions_from_broker(db)
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


# ===== Phase 4: Execution =====

@app.get("/execution", response_class=HTMLResponse)
def execution_page(request: Request, db: Session = Depends(get_db)):
    pending = db.query(TradeSignal).filter(TradeSignal.status == "pending").all()
    confirmed = db.query(TradeSignal).filter(TradeSignal.status == "confirmed").all()
    recent_executed = db.query(TradeSignal).filter(TradeSignal.status == "executed").order_by(TradeSignal.execution_time.desc()).limit(10).all()
    return templates.TemplateResponse("execution.html", {
        "request": request,
        "pending": pending,
        "confirmed": confirmed,
        "recent_executed": recent_executed,
    })


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


@app.get("/performance", response_class=HTMLResponse)
def performance_page(request: Request, db: Session = Depends(get_db)):
    from performance import compute_portfolio_performance
    perf = compute_portfolio_performance(db)
    return templates.TemplateResponse("performance.html", {
        "request": request,
        "perf": perf,
    })


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
