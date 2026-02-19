"""Unit tests for the depreciation engine."""

from datetime import date
from decimal import Decimal

import pytest

from sentient_ledger.engine.depreciation import (
    calculate_accumulated_depreciation,
    calculate_monthly_depreciation,
)
from sentient_ledger.models.enums import DepreciationConvention, DepreciationMethod


class TestStraightLine:
    def test_basic_sl(self):
        """Basic SL: $120,000 / 120 months = $1,000/mo exactly."""
        schedule = calculate_monthly_depreciation(
            cost=Decimal("120000"),
            salvage=Decimal("0"),
            life_months=120,
            method=DepreciationMethod.STRAIGHT_LINE,
            convention=DepreciationConvention.FULL_MONTH,
            acq_date=date(2024, 1, 1),
        )
        assert len(schedule) == 120
        assert schedule[0].amount == Decimal("1000.00")
        assert schedule[-1].accumulated == Decimal("120000.00")
        assert schedule[-1].net_book_value == Decimal("0.00")

    def test_sl_with_salvage(self):
        """SL with salvage: ($100,000 - $10,000) / 60 = $1,500/mo."""
        schedule = calculate_monthly_depreciation(
            cost=Decimal("100000"),
            salvage=Decimal("10000"),
            life_months=60,
            method=DepreciationMethod.STRAIGHT_LINE,
            convention=DepreciationConvention.FULL_MONTH,
            acq_date=date(2024, 1, 1),
        )
        assert len(schedule) == 60
        assert schedule[0].amount == Decimal("1500.00")
        total = sum(e.amount for e in schedule)
        assert total == Decimal("90000.00")
        assert schedule[-1].net_book_value == Decimal("10000.00")

    def test_sl_final_period_adjustment(self):
        """SL with rounding: final period adjusts so total = base exactly."""
        schedule = calculate_monthly_depreciation(
            cost=Decimal("10000"),
            salvage=Decimal("0"),
            life_months=3,
            method=DepreciationMethod.STRAIGHT_LINE,
            convention=DepreciationConvention.FULL_MONTH,
            acq_date=date(2024, 1, 1),
        )
        total = sum(e.amount for e in schedule)
        assert total == Decimal("10000.00")

    def test_sl_half_month_convention(self):
        """HALF_MONTH: first period = half of monthly amount."""
        schedule = calculate_monthly_depreciation(
            cost=Decimal("120000"),
            salvage=Decimal("0"),
            life_months=120,
            method=DepreciationMethod.STRAIGHT_LINE,
            convention=DepreciationConvention.HALF_MONTH,
            acq_date=date(2024, 1, 15),
        )
        assert schedule[0].amount == Decimal("500.00")  # half of 1000

    def test_sl_mid_month_convention(self):
        """MID_MONTH: first period prorated by day of month."""
        schedule = calculate_monthly_depreciation(
            cost=Decimal("120000"),
            salvage=Decimal("0"),
            life_months=120,
            method=DepreciationMethod.STRAIGHT_LINE,
            convention=DepreciationConvention.MID_MONTH,
            acq_date=date(2024, 1, 15),
        )
        # Jan has 31 days, remaining = 31-15+1 = 17 days, fraction = 17/31 ≈ 0.55
        assert schedule[0].amount < Decimal("1000.00")
        assert schedule[0].amount > Decimal("500.00")

    def test_sl_as_of_date(self):
        """as_of_date limits schedule output."""
        schedule = calculate_monthly_depreciation(
            cost=Decimal("120000"),
            salvage=Decimal("0"),
            life_months=120,
            method=DepreciationMethod.STRAIGHT_LINE,
            convention=DepreciationConvention.FULL_MONTH,
            acq_date=date(2024, 1, 1),
            as_of_date=date(2024, 6, 1),
        )
        assert len(schedule) == 6

    def test_sl_zero_base(self):
        """Zero depreciable base returns empty schedule."""
        schedule = calculate_monthly_depreciation(
            cost=Decimal("10000"),
            salvage=Decimal("10000"),
            life_months=120,
            method=DepreciationMethod.STRAIGHT_LINE,
            convention=DepreciationConvention.FULL_MONTH,
            acq_date=date(2024, 1, 1),
        )
        assert schedule == []

    def test_sl_negative_base(self):
        """Salvage > cost returns empty schedule."""
        schedule = calculate_monthly_depreciation(
            cost=Decimal("5000"),
            salvage=Decimal("10000"),
            life_months=60,
            method=DepreciationMethod.STRAIGHT_LINE,
            convention=DepreciationConvention.FULL_MONTH,
            acq_date=date(2024, 1, 1),
        )
        assert schedule == []


class TestDoubleDeclining:
    def test_basic_ddb(self):
        """DDB: rate = 2/life_years, switches to SL at crossover."""
        schedule = calculate_monthly_depreciation(
            cost=Decimal("100000"),
            salvage=Decimal("10000"),
            life_months=60,
            method=DepreciationMethod.DOUBLE_DECLINING,
            convention=DepreciationConvention.FULL_MONTH,
            acq_date=date(2024, 1, 1),
        )
        # First period should be higher than SL
        sl_monthly = Decimal("90000") / Decimal("60")
        assert schedule[0].amount > sl_monthly
        # Should not depreciate below salvage
        assert schedule[-1].net_book_value >= Decimal("10000")

    def test_ddb_no_below_salvage(self):
        """DDB never depreciates below salvage value."""
        schedule = calculate_monthly_depreciation(
            cost=Decimal("50000"),
            salvage=Decimal("5000"),
            life_months=60,
            method=DepreciationMethod.DOUBLE_DECLINING,
            convention=DepreciationConvention.FULL_MONTH,
            acq_date=date(2024, 1, 1),
        )
        for entry in schedule:
            assert entry.net_book_value >= Decimal("5000") - Decimal("0.01")


class TestSumOfYears:
    def test_basic_syd(self):
        """SYD: decreasing annual fractions."""
        schedule = calculate_monthly_depreciation(
            cost=Decimal("60000"),
            salvage=Decimal("0"),
            life_months=60,
            method=DepreciationMethod.SUM_OF_YEARS,
            convention=DepreciationConvention.FULL_MONTH,
            acq_date=date(2024, 1, 1),
        )
        # Year 1 monthly should be higher than year 5
        year1_avg = sum(e.amount for e in schedule[:12]) / 12
        year5_entries = schedule[48:60]
        if year5_entries:
            year5_avg = sum(e.amount for e in year5_entries) / len(year5_entries)
            assert year1_avg > year5_avg

    def test_syd_total_equals_base(self):
        """SYD total depreciation should equal depreciable base."""
        schedule = calculate_monthly_depreciation(
            cost=Decimal("60000"),
            salvage=Decimal("0"),
            life_months=60,
            method=DepreciationMethod.SUM_OF_YEARS,
            convention=DepreciationConvention.FULL_MONTH,
            acq_date=date(2024, 1, 1),
        )
        total = sum(e.amount for e in schedule)
        assert abs(total - Decimal("60000")) <= Decimal("1.00")


class TestUnsupportedMethods:
    def test_uop_raises(self):
        with pytest.raises(NotImplementedError):
            calculate_monthly_depreciation(
                cost=Decimal("100000"),
                salvage=Decimal("0"),
                life_months=60,
                method=DepreciationMethod.UNITS_OF_PRODUCTION,
                convention=DepreciationConvention.FULL_MONTH,
                acq_date=date(2024, 1, 1),
            )

    def test_macrs_raises(self):
        with pytest.raises(NotImplementedError):
            calculate_monthly_depreciation(
                cost=Decimal("100000"),
                salvage=Decimal("0"),
                life_months=60,
                method=DepreciationMethod.MACRS,
                convention=DepreciationConvention.FULL_MONTH,
                acq_date=date(2024, 1, 1),
            )


class TestAccumulated:
    def test_accumulated_depreciation(self):
        """calculate_accumulated_depreciation returns correct total."""
        acc = calculate_accumulated_depreciation(
            cost=Decimal("120000"),
            salvage=Decimal("0"),
            life_months=120,
            method=DepreciationMethod.STRAIGHT_LINE,
            convention=DepreciationConvention.FULL_MONTH,
            acq_date=date(2024, 1, 1),
            as_of_date=date(2024, 12, 1),
        )
        assert acc == Decimal("12000.00")

    def test_accumulated_full_life(self):
        """Accumulated at end of life equals depreciable base."""
        acc = calculate_accumulated_depreciation(
            cost=Decimal("100000"),
            salvage=Decimal("10000"),
            life_months=60,
            method=DepreciationMethod.STRAIGHT_LINE,
            convention=DepreciationConvention.FULL_MONTH,
            acq_date=date(2024, 1, 1),
            as_of_date=date(2029, 12, 1),
        )
        assert acc == Decimal("90000.00")
