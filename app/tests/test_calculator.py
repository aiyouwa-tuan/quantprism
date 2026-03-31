"""
Position Calculator — 100% branch coverage
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from calculator import calculate_position_size, derive_constraints, check_can_open_position


class TestCalculatePositionSize:
    def test_happy_path(self):
        """标准计算: $10000 账户, 入场$150, 止损$145, 2%风险"""
        r = calculate_position_size(10000, 150.0, 145.0, 0.02)
        # risk_budget = 10000 * 0.02 = 200
        # risk_per_share = |150 - 145| = 5
        # shares = floor(200 / 5) = 40
        assert r.shares == 40
        assert r.risk_amount == 200.0
        assert r.position_value == 6000.0
        assert abs(r.risk_pct_of_account - 0.02) < 0.001
        assert not r.is_capped

    def test_short_position(self):
        """做空: 止损价高于入场价"""
        r = calculate_position_size(10000, 100.0, 105.0, 0.02)
        # risk_per_share = |100 - 105| = 5
        # shares = floor(200 / 5) = 40
        assert r.shares == 40
        assert r.risk_amount == 200.0

    def test_stop_equals_entry(self):
        """止损 = 入场: 除零保护"""
        r = calculate_position_size(10000, 150.0, 150.0, 0.02)
        assert r.shares == 0
        assert r.risk_amount == 0

    def test_zero_account(self):
        """账户余额为零"""
        r = calculate_position_size(0, 150.0, 145.0, 0.02)
        assert r.shares == 0

    def test_zero_risk_pct(self):
        """风险比例为零"""
        r = calculate_position_size(10000, 150.0, 145.0, 0)
        assert r.shares == 0

    def test_negative_account(self):
        """负账户余额"""
        r = calculate_position_size(-5000, 150.0, 145.0, 0.02)
        assert r.shares == 0

    def test_position_capped(self):
        """仓位超过上限百分比时截断"""
        # max_position_pct = 5%, account = 10000 → max_value = 500
        # entry = 150, 所以 max shares = floor(500/150) = 3
        r = calculate_position_size(10000, 150.0, 149.0, 0.02, max_position_pct=0.05)
        assert r.is_capped
        assert r.shares == 3
        assert r.position_value == 450.0

    def test_tiny_risk_per_share(self):
        """止损很近: 大量股数"""
        r = calculate_position_size(100000, 100.0, 99.0, 0.01)
        # risk_budget = 100000 * 0.01 = 1000
        # risk_per_share = |100 - 99| = 1.0
        # shares = floor(1000 / 1) = 1000
        assert r.shares == 1000
        assert r.risk_amount == 1000.0

    def test_very_expensive_stock(self):
        """昂贵股票: 风险预算不够买一股"""
        r = calculate_position_size(1000, 5000.0, 4900.0, 0.01)
        # risk_budget = 10, risk_per_share = 100
        # shares = floor(0.1) = 0
        assert r.shares == 0

    def test_cap_reduces_to_zero(self):
        """上限极小导致股数变0"""
        r = calculate_position_size(1000, 500.0, 490.0, 0.02, max_position_pct=0.001)
        # max_value = 1, entry = 500, max shares = floor(0.002) = 0
        assert r.shares == 0


class TestDeriveConstraints:
    def test_happy_path(self):
        """10% 回撤, 2% 风险 → 5 个持仓上限"""
        r = derive_constraints(0.10, 0.02)
        assert r.max_positions == 5
        assert abs(r.max_position_pct - 0.02) < 0.001

    def test_zero_risk(self):
        """风险为零: 除零保护"""
        r = derive_constraints(0.10, 0)
        assert r.max_positions == 0

    def test_zero_drawdown(self):
        """回撤容忍度为零"""
        r = derive_constraints(0, 0.02)
        assert r.max_positions == 0

    def test_drawdown_less_than_risk(self):
        """回撤 < 单笔风险: 只能开 1 个"""
        r = derive_constraints(0.01, 0.02)
        assert r.max_positions == 1
        assert r.max_position_pct == 0.01

    def test_exact_division(self):
        """精确整除"""
        r = derive_constraints(0.20, 0.04)
        assert r.max_positions == 5

    def test_non_exact_division(self):
        """不整除: floor"""
        r = derive_constraints(0.10, 0.03)
        assert r.max_positions == 3  # floor(10/3) = 3

    def test_negative_risk(self):
        """负风险值"""
        r = derive_constraints(0.10, -0.02)
        assert r.max_positions == 0


class TestCheckCanOpenPosition:
    def test_can_open(self):
        assert check_can_open_position(2, 5) is True

    def test_at_limit(self):
        assert check_can_open_position(5, 5) is False

    def test_over_limit(self):
        assert check_can_open_position(6, 5) is False

    def test_zero_positions(self):
        assert check_can_open_position(0, 5) is True

    def test_zero_limit(self):
        assert check_can_open_position(0, 0) is False
