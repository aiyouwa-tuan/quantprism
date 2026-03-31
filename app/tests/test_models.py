"""
Data Models — CRUD tests
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from models import UserGoals, Position, TradeJournal, JournalCompliance


class TestUserGoals:
    def test_create_goals(self, db_session):
        goals = UserGoals(
            annual_return_target=0.15,
            max_drawdown=0.10,
            risk_per_trade=0.02,
            max_positions=5,
            max_position_pct=0.02,
        )
        db_session.add(goals)
        db_session.commit()

        saved = db_session.query(UserGoals).first()
        assert saved.annual_return_target == 0.15
        assert saved.max_drawdown == 0.10
        assert saved.max_positions == 5

    def test_update_goals(self, db_session):
        goals = UserGoals(annual_return_target=0.15, max_drawdown=0.10, risk_per_trade=0.02)
        db_session.add(goals)
        db_session.commit()

        goals.max_drawdown = 0.15
        db_session.commit()

        saved = db_session.query(UserGoals).first()
        assert saved.max_drawdown == 0.15


class TestPosition:
    def test_create_position(self, db_session):
        pos = Position(
            symbol="AAPL",
            market="stock",
            entry_price=150.0,
            stop_loss=145.0,
            quantity=40,
            risk_amount=200.0,
            risk_pct_of_account=0.02,
            account_balance_at_entry=10000.0,
        )
        db_session.add(pos)
        db_session.commit()

        saved = db_session.query(Position).first()
        assert saved.symbol == "AAPL"
        assert saved.is_open is True
        assert saved.quantity == 40

    def test_close_position(self, db_session):
        from datetime import datetime
        pos = Position(
            symbol="TSLA",
            entry_price=200.0,
            stop_loss=190.0,
            quantity=10,
        )
        db_session.add(pos)
        db_session.commit()

        pos.is_open = False
        pos.close_price = 210.0
        pos.close_date = datetime.utcnow()
        db_session.commit()

        saved = db_session.query(Position).first()
        assert saved.is_open is False
        assert saved.close_price == 210.0

    def test_filter_open_positions(self, db_session):
        db_session.add(Position(symbol="A", entry_price=100, stop_loss=95, quantity=10, is_open=True))
        db_session.add(Position(symbol="B", entry_price=200, stop_loss=190, quantity=5, is_open=False))
        db_session.commit()

        open_positions = db_session.query(Position).filter(Position.is_open == True).all()
        assert len(open_positions) == 1
        assert open_positions[0].symbol == "A"


class TestTradeJournal:
    def test_create_with_all_fields(self, db_session):
        journal = TradeJournal(
            symbol="AAPL",
            action="buy",
            entry_reason="突破阻力位",
            market_conditions="牛市,低波动",
            emotional_state="confident",
            vix_at_entry=15.5,
            trend_at_entry="uptrend",
            notes="计划持有一周",
        )
        db_session.add(journal)
        db_session.commit()

        saved = db_session.query(TradeJournal).first()
        assert saved.entry_reason == "突破阻力位"
        assert saved.emotional_state == "confident"
        assert saved.vix_at_entry == 15.5

    def test_create_with_minimal_fields(self, db_session):
        journal = TradeJournal(symbol="BTC", action="buy")
        db_session.add(journal)
        db_session.commit()

        saved = db_session.query(TradeJournal).first()
        assert saved.symbol == "BTC"
        assert saved.entry_reason is None
        assert saved.emotional_state is None

    def test_unicode_in_reason(self, db_session):
        journal = TradeJournal(
            symbol="AAPL",
            action="buy",
            entry_reason="技术突破，RSI超买回落后反弹",
        )
        db_session.add(journal)
        db_session.commit()

        saved = db_session.query(TradeJournal).first()
        assert "RSI超买" in saved.entry_reason


class TestJournalCompliance:
    def test_tracks_without_journal(self, db_session):
        compliance = JournalCompliance()
        db_session.add(compliance)
        db_session.commit()

        compliance.trades_without_journal = 3
        compliance.total_trades = 5
        compliance.total_journaled = 2
        db_session.commit()

        saved = db_session.query(JournalCompliance).first()
        assert saved.trades_without_journal == 3
        assert saved.total_trades == 5
