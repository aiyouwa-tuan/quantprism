"""
Performance analytics tests
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from datetime import datetime
from models import Position
from performance import compute_portfolio_performance


class TestPerformance:
    def test_empty_portfolio(self, db_session):
        perf = compute_portfolio_performance(db_session)
        assert perf["total_pnl"] == 0
        assert perf["total_trades"] == 0
        assert perf["win_rate"] == 0

    def test_with_closed_trades(self, db_session):
        # Winning trade
        p1 = Position(symbol="AAPL", market="stock", entry_price=100, stop_loss=95,
                      quantity=10, is_open=False, close_price=110,
                      entry_date=datetime(2024, 1, 1), close_date=datetime(2024, 2, 1))
        # Losing trade
        p2 = Position(symbol="TSLA", market="stock", entry_price=200, stop_loss=190,
                      quantity=5, is_open=False, close_price=180,
                      entry_date=datetime(2024, 2, 1), close_date=datetime(2024, 3, 1))
        db_session.add_all([p1, p2])
        db_session.commit()

        perf = compute_portfolio_performance(db_session)
        # AAPL: (110-100)*10 = 100, TSLA: (180-200)*5 = -100
        assert perf["total_pnl"] == 0
        assert perf["total_trades"] == 2
        assert perf["win_rate"] == 0.5

    def test_by_market_breakdown(self, db_session):
        p1 = Position(symbol="AAPL", market="stock", entry_price=100, stop_loss=95,
                      quantity=10, is_open=False, close_price=110,
                      entry_date=datetime(2024, 1, 1), close_date=datetime(2024, 2, 1))
        p2 = Position(symbol="BTC", market="crypto", entry_price=40000, stop_loss=38000,
                      quantity=0.1, is_open=False, close_price=45000,
                      entry_date=datetime(2024, 1, 1), close_date=datetime(2024, 3, 1))
        db_session.add_all([p1, p2])
        db_session.commit()

        perf = compute_portfolio_performance(db_session)
        assert "stock" in perf["by_market"]
        assert "crypto" in perf["by_market"]
        assert perf["by_market"]["stock"]["count"] == 1
        assert perf["by_market"]["crypto"]["count"] == 1

    def test_monthly_returns(self, db_session):
        p1 = Position(symbol="AAPL", market="stock", entry_price=100, stop_loss=95,
                      quantity=10, is_open=False, close_price=110,
                      entry_date=datetime(2024, 1, 1), close_date=datetime(2024, 1, 15))
        p2 = Position(symbol="MSFT", market="stock", entry_price=300, stop_loss=290,
                      quantity=5, is_open=False, close_price=310,
                      entry_date=datetime(2024, 2, 1), close_date=datetime(2024, 2, 15))
        db_session.add_all([p1, p2])
        db_session.commit()

        perf = compute_portfolio_performance(db_session)
        assert len(perf["monthly_returns"]) == 2
        assert perf["monthly_returns"][0]["month"] == "2024-01"

    def test_open_positions_excluded(self, db_session):
        p1 = Position(symbol="AAPL", market="stock", entry_price=100, stop_loss=95,
                      quantity=10, is_open=True)  # still open
        db_session.add(p1)
        db_session.commit()

        perf = compute_portfolio_performance(db_session)
        assert perf["total_trades"] == 0  # open positions not counted
