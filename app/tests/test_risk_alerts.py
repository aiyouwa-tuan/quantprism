"""
Risk engine + alerts tests
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from models import UserGoals, Position, AlertConfig, AlertHistory
from risk_engine import compute_portfolio_risk
from unittest.mock import patch


class TestPortfolioRisk:
    def test_empty_portfolio(self, db_session):
        goals = UserGoals(annual_return_target=0.15, max_drawdown=0.10, risk_per_trade=0.02, max_positions=5)
        db_session.add(goals)
        db_session.commit()

        risk = compute_portfolio_risk(db_session)
        assert risk["total_risk_pct"] == 0
        assert risk["position_count"] == 0
        assert risk["drawdown_headroom"] == 0.10

    def test_with_positions(self, db_session):
        goals = UserGoals(annual_return_target=0.15, max_drawdown=0.10, risk_per_trade=0.02, max_positions=5)
        db_session.add(goals)
        pos = Position(symbol="AAPL", entry_price=150, stop_loss=145, quantity=40,
                       risk_pct_of_account=0.02, account_balance_at_entry=10000)
        db_session.add(pos)
        db_session.commit()

        risk = compute_portfolio_risk(db_session)
        assert risk["total_risk_pct"] == 0.02
        assert risk["position_count"] == 1
        assert risk["max_single_risk"] == 0.02
        assert "vix" in risk

    def test_high_risk_positions_flagged(self, db_session):
        goals = UserGoals(annual_return_target=0.15, max_drawdown=0.10, risk_per_trade=0.02, max_positions=5)
        db_session.add(goals)
        pos = Position(symbol="TSLA", entry_price=200, stop_loss=180, quantity=50,
                       risk_pct_of_account=0.05, account_balance_at_entry=20000)
        db_session.add(pos)
        db_session.commit()

        risk = compute_portfolio_risk(db_session)
        assert len(risk["positions_at_risk"]) == 1
        assert risk["positions_at_risk"][0]["symbol"] == "TSLA"


class TestAlertRateLimiting:
    def test_rate_limit_blocks_duplicate(self, db_session):
        config = AlertConfig(is_active=True, rate_limit_minutes=60)
        db_session.add(config)
        db_session.commit()

        from alerts import send_alert

        # First alert should go through (but not actually deliver since no webhook configured)
        result1 = send_alert(db_session, "test", "Test 1", "Body 1")
        # Second same-type alert within rate limit should be blocked
        result2 = send_alert(db_session, "test", "Test 2", "Body 2")
        assert result2["delivered"] is False
        assert "频率限制" in result2["message"]

    def test_different_types_not_rate_limited(self, db_session):
        config = AlertConfig(is_active=True, rate_limit_minutes=60)
        db_session.add(config)
        db_session.commit()

        from alerts import send_alert
        result1 = send_alert(db_session, "type_a", "A", "A")
        result2 = send_alert(db_session, "type_b", "B", "B")
        # type_b should not be rate-limited by type_a
        assert "频率限制" not in result2.get("message", "")

    def test_disabled_config_skips(self, db_session):
        config = AlertConfig(is_active=False)
        db_session.add(config)
        db_session.commit()

        from alerts import send_alert
        result = send_alert(db_session, "test", "Title", "Body")
        assert result["delivered"] is False
        assert "禁用" in result["message"]

    def test_no_config_skips(self, db_session):
        from alerts import send_alert
        result = send_alert(db_session, "test", "Title", "Body")
        assert result["delivered"] is False


class TestMarketRegime:
    def test_low_vol(self):
        from market_data import detect_market_regime
        r = detect_market_regime(vix_value=12)
        assert r["regime"] == "low_vol"

    def test_normal(self):
        from market_data import detect_market_regime
        r = detect_market_regime(vix_value=17)
        assert r["regime"] == "normal"

    def test_mid_vol(self):
        from market_data import detect_market_regime
        r = detect_market_regime(vix_value=25)
        assert r["regime"] == "mid_vol"

    def test_high_vol(self):
        from market_data import detect_market_regime
        r = detect_market_regime(vix_value=35)
        assert r["regime"] == "high_vol"
