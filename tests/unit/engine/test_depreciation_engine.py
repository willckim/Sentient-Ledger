"""Depreciation engine unit tests — core calculation correctness."""

from datetime import date
from decimal import Decimal

import pytest

from sentient_ledger.engine.depreciation import (
    MonthlyDepreciation,
    calculate_accumulated_depreciation,
    calculate_monthly_depreciation,
)
from sentient_ledger.models.enums import DepreciationConvention, DepreciationMethod


class TestStraightLineExact:
    """SL calculations exact to the penny."""

    def test_even_division(self):
        """$120,000 / 120 months = exactly $1,000.00 each."""
        sched = calculate_monthly_depreciation(
            Decimal("120000"), Decimal("0"), 120,
            DepreciationMethod.STRAIGHT_LINE,
            DepreciationConvention.FULL_MONTH,
            date(2024, 1, 1),
        )
        assert all(e.amount == Decimal("1000.00") for e in sched)
        assert sched[-1].accumulated == Decimal("120000.00")

    def test_uneven_division_adjusts_final(self):
        """$10,000 / 3 = $3,333.33 × 2 + final adjustment."""
        sched = calculate_monthly_depreciation(
            Decimal("10000"), Decimal("0"), 3,
            DepreciationMethod.STRAIGHT_LINE,
            DepreciationConvention.FULL_MONTH,
            date(2024, 1, 1),
        )
        assert len(sched) == 3
        total = sum(e.amount for e in sched)
        assert total == Decimal("10000.00"), f"Total was {total}"

    def test_with_salvage(self):
        sched = calculate_monthly_depreciation(
            Decimal("100000"), Decimal("10000"), 60,
            DepreciationMethod.STRAIGHT_LINE,
            DepreciationConvention.FULL_MONTH,
            date(2024, 1, 1),
        )
        total = sum(e.amount for e in sched)
        assert total == Decimal("90000.00")
        assert sched[-1].net_book_value == Decimal("10000.00")

    def test_periods_are_sequential(self):
        sched = calculate_monthly_depreciation(
            Decimal("12000"), Decimal("0"), 12,
            DepreciationMethod.STRAIGHT_LINE,
            DepreciationConvention.FULL_MONTH,
            date(2024, 1, 1),
        )
        periods = [e.period for e in sched]
        expected = [f"2024-{m:02d}" for m in range(1, 13)]
        assert periods == expected

    def test_accumulated_monotonic(self):
        sched = calculate_monthly_depreciation(
            Decimal("60000"), Decimal("0"), 60,
            DepreciationMethod.STRAIGHT_LINE,
            DepreciationConvention.FULL_MONTH,
            date(2024, 1, 1),
        )
        for i in range(1, len(sched)):
            assert sched[i].accumulated >= sched[i - 1].accumulated

    def test_nbv_monotonic_decreasing(self):
        sched = calculate_monthly_depreciation(
            Decimal("60000"), Decimal("0"), 60,
            DepreciationMethod.STRAIGHT_LINE,
            DepreciationConvention.FULL_MONTH,
            date(2024, 1, 1),
        )
        for i in range(1, len(sched)):
            assert sched[i].net_book_value <= sched[i - 1].net_book_value


class TestConventions:
    def test_full_month(self):
        sched = calculate_monthly_depreciation(
            Decimal("12000"), Decimal("0"), 12,
            DepreciationMethod.STRAIGHT_LINE,
            DepreciationConvention.FULL_MONTH,
            date(2024, 3, 15),
        )
        assert sched[0].amount == Decimal("1000.00")

    def test_half_month(self):
        sched = calculate_monthly_depreciation(
            Decimal("12000"), Decimal("0"), 12,
            DepreciationMethod.STRAIGHT_LINE,
            DepreciationConvention.HALF_MONTH,
            date(2024, 3, 15),
        )
        assert sched[0].amount == Decimal("500.00")

    def test_mid_month(self):
        sched = calculate_monthly_depreciation(
            Decimal("120000"), Decimal("0"), 120,
            DepreciationMethod.STRAIGHT_LINE,
            DepreciationConvention.MID_MONTH,
            date(2024, 1, 15),
        )
        # 31 days in Jan, 17 remaining, fraction = 17/31 ≈ 0.55
        assert Decimal("500") < sched[0].amount < Decimal("600")


class TestDDB:
    def test_first_month_higher_than_sl(self):
        sched = calculate_monthly_depreciation(
            Decimal("100000"), Decimal("10000"), 60,
            DepreciationMethod.DOUBLE_DECLINING,
            DepreciationConvention.FULL_MONTH,
            date(2024, 1, 1),
        )
        sl_monthly = (Decimal("100000") - Decimal("10000")) / 60
        assert sched[0].amount > sl_monthly

    def test_never_below_salvage(self):
        sched = calculate_monthly_depreciation(
            Decimal("50000"), Decimal("5000"), 60,
            DepreciationMethod.DOUBLE_DECLINING,
            DepreciationConvention.FULL_MONTH,
            date(2024, 1, 1),
        )
        for e in sched:
            assert e.net_book_value >= Decimal("4999.99")


class TestSYD:
    def test_decreasing_pattern(self):
        sched = calculate_monthly_depreciation(
            Decimal("60000"), Decimal("0"), 60,
            DepreciationMethod.SUM_OF_YEARS,
            DepreciationConvention.FULL_MONTH,
            date(2024, 1, 1),
        )
        y1 = sum(e.amount for e in sched[:12])
        y5 = sum(e.amount for e in sched[48:60])
        assert y1 > y5


class TestEdgeCases:
    def test_zero_life(self):
        sched = calculate_monthly_depreciation(
            Decimal("10000"), Decimal("0"), 0,
            DepreciationMethod.STRAIGHT_LINE,
            DepreciationConvention.FULL_MONTH,
            date(2024, 1, 1),
        )
        assert sched == []

    def test_salvage_equals_cost(self):
        sched = calculate_monthly_depreciation(
            Decimal("10000"), Decimal("10000"), 60,
            DepreciationMethod.STRAIGHT_LINE,
            DepreciationConvention.FULL_MONTH,
            date(2024, 1, 1),
        )
        assert sched == []
