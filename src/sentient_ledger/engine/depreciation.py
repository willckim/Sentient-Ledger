"""Pure-function depreciation calculator.

All arithmetic uses Decimal. No LLM, no state machine coupling.
Supports: STRAIGHT_LINE (full, all 5 conventions), DOUBLE_DECLINING, SUM_OF_YEARS.
Raises NotImplementedError for UNITS_OF_PRODUCTION and MACRS.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from sentient_ledger.models.enums import DepreciationConvention, DepreciationMethod

TWO_DP = Decimal("0.01")


@dataclass(frozen=True)
class MonthlyDepreciation:
    """One month of depreciation output."""

    period: str  # YYYY-MM
    amount: Decimal
    accumulated: Decimal
    net_book_value: Decimal


def _round2(value: Decimal) -> Decimal:
    return value.quantize(TWO_DP, rounding=ROUND_HALF_UP)


def _month_diff(start: date, end: date) -> int:
    """Number of whole months from start to end (inclusive of start month)."""
    return (end.year - start.year) * 12 + (end.month - start.month)


def _add_months(d: date, months: int) -> date:
    """Return the first day of the month that is `months` after d."""
    total = d.year * 12 + (d.month - 1) + months
    y, m = divmod(total, 12)
    return date(y, m + 1, 1)


def _first_period_fraction(
    convention: DepreciationConvention,
    acq_date: date,
) -> Decimal:
    """Return the fraction of a full month's depreciation for the first period."""
    if convention == DepreciationConvention.FULL_MONTH:
        return Decimal("1")

    if convention == DepreciationConvention.HALF_MONTH:
        return Decimal("0.5")

    if convention == DepreciationConvention.MID_MONTH:
        import calendar

        days_in_month = calendar.monthrange(acq_date.year, acq_date.month)[1]
        remaining_days = days_in_month - acq_date.day + 1
        return _round2(Decimal(remaining_days) / Decimal(days_in_month))

    if convention == DepreciationConvention.HALF_YEAR:
        return Decimal("6")  # special: represents 6 months in year 1

    if convention == DepreciationConvention.MID_QUARTER:
        quarter_month = ((acq_date.month - 1) % 3)  # 0, 1, 2 within quarter
        mid_quarter_months = Decimal("1.5") - Decimal(str(quarter_month))
        return mid_quarter_months

    return Decimal("1")


def _last_period_fraction(
    convention: DepreciationConvention,
    acq_date: date,
) -> Decimal | None:
    """Return the fraction for the final period if convention requires it, else None."""
    if convention == DepreciationConvention.HALF_MONTH:
        return Decimal("0.5")
    if convention == DepreciationConvention.HALF_YEAR:
        # Remaining months in final year = 12 - 6 = 6 months equivalent
        return Decimal("6")  # handled specially
    return None


def calculate_monthly_depreciation(
    cost: Decimal,
    salvage: Decimal,
    life_months: int,
    method: DepreciationMethod,
    convention: DepreciationConvention,
    acq_date: date,
    as_of_date: date | None = None,
) -> list[MonthlyDepreciation]:
    """Calculate a complete monthly depreciation schedule.

    Returns a list of MonthlyDepreciation from acquisition through end of useful life.
    """
    if method == DepreciationMethod.UNITS_OF_PRODUCTION:
        raise NotImplementedError("Units of Production not implemented")
    if method == DepreciationMethod.MACRS:
        raise NotImplementedError("MACRS not implemented")

    depreciable_base = cost - salvage
    if depreciable_base <= 0 or life_months <= 0:
        return []

    if method == DepreciationMethod.STRAIGHT_LINE:
        return _straight_line(cost, salvage, depreciable_base, life_months, convention, acq_date, as_of_date)
    if method == DepreciationMethod.DOUBLE_DECLINING:
        return _double_declining(cost, salvage, depreciable_base, life_months, convention, acq_date, as_of_date)
    if method == DepreciationMethod.SUM_OF_YEARS:
        return _sum_of_years(cost, salvage, depreciable_base, life_months, convention, acq_date, as_of_date)

    raise ValueError(f"Unsupported method: {method}")


def _straight_line(
    cost: Decimal,
    salvage: Decimal,
    depreciable_base: Decimal,
    life_months: int,
    convention: DepreciationConvention,
    acq_date: date,
    as_of_date: date | None,
) -> list[MonthlyDepreciation]:
    monthly_amount = _round2(depreciable_base / Decimal(life_months))

    schedule: list[MonthlyDepreciation] = []
    accumulated = Decimal("0")
    period_start = date(acq_date.year, acq_date.month, 1)

    # Handle HALF_YEAR convention: the total number of schedule periods
    # extends by the partial first/last year adjustment
    if convention == DepreciationConvention.HALF_YEAR:
        # First 6 months get depreciation in year 1, then full months,
        # then last 6 months extend beyond nominal life
        total_periods = life_months + 6  # 6 extra months at the end
    else:
        first_frac = _first_period_fraction(convention, acq_date)
        if convention == DepreciationConvention.MID_QUARTER:
            # Extra periods at end to compensate for partial first period
            extra = Decimal(str(life_months)) * (Decimal("1") - first_frac / Decimal(str(life_months)))
            total_periods = life_months + 1  # one extra month at most
        else:
            total_periods = life_months

    max_periods = life_months + 12  # safety bound
    period_idx = 0

    while accumulated < depreciable_base and period_idx < max_periods:
        current_date = _add_months(period_start, period_idx)
        period_str = f"{current_date.year:04d}-{current_date.month:02d}"

        if as_of_date and current_date > as_of_date:
            break

        # Determine this period's amount
        remaining = depreciable_base - accumulated
        if remaining <= 0:
            break

        if period_idx == 0:
            # First period: apply convention
            if convention == DepreciationConvention.HALF_YEAR:
                # Spread 6 months' worth into first month (annual/12*6 = monthly*6)
                amt = _round2(monthly_amount * Decimal("6") / Decimal("12"))
                # Actually for half-year: first year gets 6 months of depreciation
                # We'll give half a monthly amount for the first period
                amt = _round2(monthly_amount * Decimal("0.5"))
            elif convention == DepreciationConvention.MID_QUARTER:
                frac = _first_period_fraction(convention, acq_date)
                amt = _round2(monthly_amount * frac)
            else:
                frac = _first_period_fraction(convention, acq_date)
                amt = _round2(monthly_amount * frac)
        else:
            amt = monthly_amount

        # Clamp to remaining base
        amt = min(amt, remaining)

        # Final period adjustment: if remaining after this period would be < a full period
        if remaining - amt < monthly_amount and remaining - amt > 0:
            # Check if this should be the last period
            if period_idx >= life_months - 2:
                amt = remaining

        accumulated += amt
        nbv = cost - accumulated

        schedule.append(MonthlyDepreciation(
            period=period_str,
            amount=amt,
            accumulated=accumulated,
            net_book_value=nbv,
        ))

        period_idx += 1

    # Final adjustment: ensure accumulated == depreciable_base exactly
    if schedule and accumulated != depreciable_base:
        diff = depreciable_base - accumulated
        if abs(diff) <= Decimal("1.00"):
            last = schedule[-1]
            new_amt = last.amount + diff
            new_acc = last.accumulated + diff
            schedule[-1] = MonthlyDepreciation(
                period=last.period,
                amount=new_amt,
                accumulated=new_acc,
                net_book_value=cost - new_acc,
            )

    return schedule


def _double_declining(
    cost: Decimal,
    salvage: Decimal,
    depreciable_base: Decimal,
    life_months: int,
    convention: DepreciationConvention,
    acq_date: date,
    as_of_date: date | None,
) -> list[MonthlyDepreciation]:
    """Double-declining balance with switch to straight-line at crossover."""
    # Monthly DDB rate
    life_years = Decimal(str(life_months)) / Decimal("12")
    annual_rate = Decimal("2") / life_years if life_years > 0 else Decimal("0")
    monthly_rate = annual_rate / Decimal("12")

    schedule: list[MonthlyDepreciation] = []
    accumulated = Decimal("0")
    period_start = date(acq_date.year, acq_date.month, 1)
    book_value = cost

    for period_idx in range(life_months + 12):  # safety bound
        current_date = _add_months(period_start, period_idx)
        period_str = f"{current_date.year:04d}-{current_date.month:02d}"

        if as_of_date and current_date > as_of_date:
            break

        remaining = depreciable_base - accumulated
        if remaining <= Decimal("0.01"):
            break

        # DDB amount
        ddb_amt = _round2(book_value * monthly_rate)

        # SL amount for remaining life
        remaining_months = life_months - period_idx
        if remaining_months > 0:
            sl_amt = _round2(remaining / Decimal(str(remaining_months)))
        else:
            sl_amt = remaining

        # Apply convention to first period
        if period_idx == 0:
            frac = _first_period_fraction(convention, acq_date)
            if convention not in (DepreciationConvention.HALF_YEAR, DepreciationConvention.MID_QUARTER):
                ddb_amt = _round2(ddb_amt * frac)
                sl_amt = _round2(sl_amt * frac)

        # Switch to SL when it gives higher depreciation
        amt = max(ddb_amt, sl_amt)

        # Clamp: don't depreciate below salvage
        max_depr = book_value - salvage
        if max_depr <= 0:
            break
        amt = min(amt, max_depr, remaining)

        if amt <= 0:
            break

        accumulated += amt
        book_value -= amt

        schedule.append(MonthlyDepreciation(
            period=period_str,
            amount=amt,
            accumulated=accumulated,
            net_book_value=book_value,
        ))

    return schedule


def _sum_of_years(
    cost: Decimal,
    salvage: Decimal,
    depreciable_base: Decimal,
    life_months: int,
    convention: DepreciationConvention,
    acq_date: date,
    as_of_date: date | None,
) -> list[MonthlyDepreciation]:
    """Sum-of-years-digits: annual fraction = remaining_years / sum_of_digits, monthly = annual/12."""
    life_years = life_months // 12
    if life_years <= 0:
        life_years = 1
    sum_of_digits = Decimal(str(life_years * (life_years + 1) // 2))

    schedule: list[MonthlyDepreciation] = []
    accumulated = Decimal("0")
    period_start = date(acq_date.year, acq_date.month, 1)

    for period_idx in range(life_months + 12):
        current_date = _add_months(period_start, period_idx)
        period_str = f"{current_date.year:04d}-{current_date.month:02d}"

        if as_of_date and current_date > as_of_date:
            break

        remaining_base = depreciable_base - accumulated
        if remaining_base <= Decimal("0.01"):
            break

        # Determine which "year" of the asset's life this month falls in
        year_idx = period_idx // 12  # 0-based year
        remaining_years = Decimal(str(life_years - year_idx))
        if remaining_years <= 0:
            break

        annual_fraction = remaining_years / sum_of_digits
        annual_depr = _round2(depreciable_base * annual_fraction)
        monthly_depr = _round2(annual_depr / Decimal("12"))

        # Convention for first period
        if period_idx == 0:
            frac = _first_period_fraction(convention, acq_date)
            if convention not in (DepreciationConvention.HALF_YEAR, DepreciationConvention.MID_QUARTER):
                monthly_depr = _round2(monthly_depr * frac)

        amt = min(monthly_depr, remaining_base)
        if amt <= 0:
            break

        accumulated += amt
        nbv = cost - accumulated

        schedule.append(MonthlyDepreciation(
            period=period_str,
            amount=amt,
            accumulated=accumulated,
            net_book_value=nbv,
        ))

    # Final adjustment
    if schedule and accumulated != depreciable_base:
        diff = depreciable_base - accumulated
        if abs(diff) <= Decimal("1.00"):
            last = schedule[-1]
            new_amt = last.amount + diff
            new_acc = last.accumulated + diff
            schedule[-1] = MonthlyDepreciation(
                period=last.period,
                amount=new_amt,
                accumulated=new_acc,
                net_book_value=cost - new_acc,
            )

    return schedule


def calculate_accumulated_depreciation(
    cost: Decimal,
    salvage: Decimal,
    life_months: int,
    method: DepreciationMethod,
    convention: DepreciationConvention,
    acq_date: date,
    as_of_date: date,
) -> Decimal:
    """Return total accumulated depreciation as of a given date."""
    schedule = calculate_monthly_depreciation(
        cost, salvage, life_months, method, convention, acq_date, as_of_date,
    )
    if not schedule:
        return Decimal("0")
    return schedule[-1].accumulated
