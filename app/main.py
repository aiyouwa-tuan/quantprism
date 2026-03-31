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

from models import init_db, get_db, UserGoals, Position, TradeJournal, JournalCompliance, Base, engine
from calculator import calculate_position_size, derive_constraints, check_can_open_position
from schemas import GoalsCreate, PositionCreate, CalculateRequest, PositionClose

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

    max_position_pct = 1.0
    if goals and goals.max_position_pct:
        max_position_pct = goals.max_position_pct

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
