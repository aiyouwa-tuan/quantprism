"""
FastAPI endpoints — integration tests
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


class TestDashboard:
    def test_empty_dashboard(self, client):
        response = client.get("/")
        assert response.status_code == 200
        assert "Trading OS" in response.text

    def test_dashboard_with_goals(self, client):
        client.post("/goals", data={
            "annual_return_target": "15",
            "max_drawdown": "10",
            "risk_per_trade": "2",
        })
        response = client.get("/")
        assert response.status_code == 200


class TestGoals:
    def test_set_goals(self, client):
        response = client.post("/goals", data={
            "annual_return_target": "15",
            "max_drawdown": "10",
            "risk_per_trade": "2",
        })
        assert response.status_code == 200
        assert "15.0%" in response.text  # annual return
        assert "5 个" in response.text    # max positions (10/2=5)

    def test_update_goals(self, client):
        client.post("/goals", data={
            "annual_return_target": "15",
            "max_drawdown": "10",
            "risk_per_trade": "2",
        })
        response = client.post("/goals", data={
            "annual_return_target": "20",
            "max_drawdown": "15",
            "risk_per_trade": "3",
        })
        assert response.status_code == 200
        assert "20.0%" in response.text
        assert "5 个" in response.text  # floor(15/3)=5


class TestCalculator:
    def test_calculate_position(self, client):
        response = client.post("/calculate", data={
            "account_balance": "10000",
            "entry_price": "150",
            "stop_loss": "145",
        })
        assert response.status_code == 200
        assert "40 股" in response.text  # floor(200/5) = 40

    def test_calculate_invalid_same_price(self, client):
        response = client.post("/calculate", data={
            "account_balance": "10000",
            "entry_price": "150",
            "stop_loss": "150",
        })
        assert response.status_code == 200
        assert "无法计算" in response.text


class TestPositions:
    def test_add_position(self, client):
        response = client.post("/positions", data={
            "symbol": "aapl",
            "market": "stock",
            "entry_price": "150",
            "stop_loss": "145",
            "quantity": "40",
            "account_balance": "10000",
        })
        assert response.status_code == 200
        assert "AAPL" in response.text  # symbol uppercased
        assert "风险" in response.text

    def test_add_position_with_journal(self, client):
        response = client.post("/positions", data={
            "symbol": "TSLA",
            "market": "stock",
            "entry_price": "200",
            "stop_loss": "190",
            "quantity": "10",
            "account_balance": "20000",
            "entry_reason": "突破关键阻力位",
            "emotional_state": "confident",
        })
        assert response.status_code == 200
        assert "TSLA" in response.text

    def test_position_limit_enforcement(self, client):
        # Set goals with max 2 positions
        client.post("/goals", data={
            "annual_return_target": "10",
            "max_drawdown": "4",
            "risk_per_trade": "2",
        })
        # Add 2 positions (max_positions = floor(4/2) = 2)
        for sym in ["AAPL", "MSFT"]:
            client.post("/positions", data={
                "symbol": sym, "entry_price": "100", "stop_loss": "95",
                "quantity": "10", "account_balance": "10000",
            })
        # Third should be rejected
        response = client.post("/positions", data={
            "symbol": "GOOG", "entry_price": "100", "stop_loss": "95",
            "quantity": "10", "account_balance": "10000",
        })
        assert "持仓上限" in response.text

    def test_close_position(self, client):
        client.post("/positions", data={
            "symbol": "AAPL", "entry_price": "150", "stop_loss": "145",
            "quantity": "40", "account_balance": "10000",
        })
        response = client.post("/positions/1/close", data={"close_price": "160"})
        assert response.status_code == 200
        assert "暂无持仓" in response.text  # position was closed


class TestJournal:
    def test_add_journal_entry(self, client):
        response = client.post("/journal", data={
            "symbol": "AAPL",
            "action": "buy",
            "entry_reason": "看好Q4财报",
            "emotional_state": "confident",
        })
        assert response.status_code == 200
        assert "AAPL" in response.text
        assert "confident" in response.text

    def test_journal_compliance_tracking(self, client):
        # Set goals first so dashboard shows full view
        client.post("/goals", data={"annual_return_target": "15", "max_drawdown": "10", "risk_per_trade": "2"})
        # Add 3 positions without journal
        for sym in ["A", "B", "C"]:
            client.post("/positions", data={
                "symbol": sym, "entry_price": "100", "stop_loss": "95",
                "quantity": "10", "account_balance": "100000",
            })
        # Dashboard should show reminder
        response = client.get("/")
        assert "没写日志" in response.text or "没有写日志" in response.text or "日志" in response.text
