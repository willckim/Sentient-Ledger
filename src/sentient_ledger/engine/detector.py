"""Error detection logic for asset depreciation schedules.

Takes asset register data, GL balances, and depreciation schedules,
recalculates expected values, and detects discrepancies.

Detection strategies are ordered by priority. Once a primary finding
is established for an asset, secondary checks are skipped to avoid
false positives from cascading effects.
"""

from __future__ import annotations

import time
import uuid
from datetime import date
from decimal import Decimal

from sentient_ledger.engine.depreciation import (
    _round2,
    calculate_monthly_depreciation,
)
from sentient_ledger.models.enums import (
    AssetStatus,
    AssetTriggerReason,
    DepreciationConvention,
    DepreciationMethod,
    SelfHealPatternId,
)
from sentient_ledger.models.eval import (
    DetectionFinding,
    DetectionResult,
    DepreciationEntry,
    GLBalance,
    ScenarioAssetRecord,
)


def _parse_date(s: str) -> date:
    """Parse YYYY-MM-DD string to date."""
    parts = s.split("-")
    return date(int(parts[0]), int(parts[1]), int(parts[2]))


def _period_to_date(period: str) -> date:
    """Convert YYYY-MM period string to first-of-month date."""
    parts = period.split("-")
    return date(int(parts[0]), int(parts[1]), 1)


def detect_errors(
    asset_register: list[ScenarioAssetRecord],
    gl_balances: list[GLBalance],
    depreciation_schedule: list[DepreciationEntry],
    as_of_date: date | None = None,
) -> DetectionResult:
    """Run all detection strategies against the provided data."""
    start_time = time.monotonic()
    findings: list[DetectionFinding] = []

    # Index schedules by asset_id
    schedule_by_asset: dict[str, list[DepreciationEntry]] = {}
    for entry in depreciation_schedule:
        schedule_by_asset.setdefault(entry.asset_id, []).append(entry)
    for entries in schedule_by_asset.values():
        entries.sort(key=lambda e: e.period)

    # Track which assets already have findings to avoid FP cascades
    flagged_assets: set[str] = set()

    for asset in asset_register:
        asset_schedule = schedule_by_asset.get(asset.asset_id, [])
        acq_date = _parse_date(asset.acquisition_date)

        if asset.depreciation_method in (
            DepreciationMethod.UNITS_OF_PRODUCTION,
            DepreciationMethod.MACRS,
        ):
            continue

        depreciable_base = asset.cost - asset.salvage_value
        if depreciable_base <= 0 and not asset_schedule:
            continue

        # Calculate expected schedule — bound to actual schedule's time range
        # to avoid FP "missing period" flags beyond the data window
        effective_as_of = as_of_date
        if asset_schedule and not effective_as_of:
            last_period = max(e.period for e in asset_schedule)
            effective_as_of = _period_to_date(last_period)

        try:
            expected = calculate_monthly_depreciation(
                cost=asset.cost,
                salvage=asset.salvage_value,
                life_months=asset.useful_life_months,
                method=asset.depreciation_method,
                convention=asset.convention,
                acq_date=acq_date,
                as_of_date=effective_as_of,
            )
        except (NotImplementedError, ValueError):
            continue

        # --- Lifecycle checks first (independent of calculation) ---
        _check_lifecycle(asset, asset_schedule, findings, flagged_assets)

        # --- Primary checks: salvage, method, convention ---
        # Stop after first primary match to avoid cascade FPs
        if asset.asset_id not in flagged_assets:
            if _check_salvage_value(asset, asset_schedule, expected, findings):
                flagged_assets.add(asset.asset_id)

        if asset.asset_id not in flagged_assets:
            if _check_method(asset, asset_schedule, expected, findings):
                flagged_assets.add(asset.asset_id)

        if asset.asset_id not in flagged_assets:
            if _check_convention(asset, asset_schedule, expected, findings):
                flagged_assets.add(asset.asset_id)

        # --- Temporal checks (missing periods, duplicates) ---
        if asset.asset_id not in flagged_assets:
            if _check_missing_periods(asset, asset_schedule, expected, findings):
                flagged_assets.add(asset.asset_id)

        # --- Useful life check ---
        if asset.asset_id not in flagged_assets:
            if _check_useful_life(asset, asset_schedule, expected, findings):
                flagged_assets.add(asset.asset_id)

        # --- Rounding/accumulated check (lowest priority, only if no other issue) ---
        if asset.asset_id not in flagged_assets:
            if _check_rounding(asset, asset_schedule, expected, findings):
                flagged_assets.add(asset.asset_id)

        # --- Salvage-exceeds-cost check (only if not already flagged) ---
        if depreciable_base <= 0 and asset_schedule and asset.asset_id not in flagged_assets:
            findings.append(_make_finding(
                error_type=AssetTriggerReason.DEPRECIATION_VARIANCE_EXCEEDS_THRESHOLD,
                asset_ids=[asset.asset_id],
                description=f"Salvage ${asset.salvage_value} >= cost ${asset.cost} but depreciation entries exist",
                confidence=0.95,
                pattern_id=SelfHealPatternId.AW_004,
            ))
            flagged_assets.add(asset.asset_id)

    # --- Cross-asset checks ---
    _check_gl_balances(asset_register, depreciation_schedule, gl_balances, findings)
    _check_duplicate_entries(asset_register, depreciation_schedule, findings)

    elapsed = (time.monotonic() - start_time) * 1000
    return DetectionResult(
        findings=findings,
        errors_detected=len(findings),
        execution_time_ms=round(elapsed, 2),
    )


def _make_finding(
    error_type: AssetTriggerReason,
    asset_ids: list[str],
    description: str,
    expected: Decimal | None = None,
    actual: Decimal | None = None,
    variance: Decimal | None = None,
    confidence: float = 0.9,
    pattern_id: SelfHealPatternId | None = None,
    corrected_amount: Decimal | None = None,
) -> DetectionFinding:
    return DetectionFinding(
        finding_id=str(uuid.uuid4()),
        error_type=error_type,
        affected_asset_ids=asset_ids,
        description=description,
        expected_value=expected,
        actual_value=actual,
        variance=variance,
        confidence=confidence,
        self_healable=pattern_id is not None,
        pattern_id=pattern_id,
        corrected_amount=corrected_amount,
    )


def _check_salvage_value(
    asset: ScenarioAssetRecord,
    actual_schedule: list[DepreciationEntry],
    expected_schedule: list,
    findings: list[DetectionFinding],
) -> bool:
    """Check if depreciation was calculated using cost instead of cost-salvage (AW-004).
    Returns True if finding was added."""
    if not actual_schedule or asset.salvage_value <= 0:
        return False

    depreciable_base = asset.cost - asset.salvage_value
    wrong_monthly = _round2(asset.cost / Decimal(str(asset.useful_life_months)))
    correct_monthly = _round2(depreciable_base / Decimal(str(asset.useful_life_months)))

    if wrong_monthly == correct_monthly:
        return False

    # Check middle periods (not first/last which may have convention adjustments)
    check_entries = actual_schedule[1:6] if len(actual_schedule) > 2 else actual_schedule
    mismatches = 0
    for entry in check_entries:
        if abs(entry.amount - wrong_monthly) < abs(entry.amount - correct_monthly):
            mismatches += 1

    if mismatches >= 1:
        total_actual = sum(e.amount for e in actual_schedule)
        total_expected = sum(e.amount for e in expected_schedule)
        if abs(total_actual - total_expected) > Decimal("1.00"):
            findings.append(_make_finding(
                error_type=AssetTriggerReason.DEPRECIATION_VARIANCE_EXCEEDS_THRESHOLD,
                asset_ids=[asset.asset_id],
                description=f"Salvage value ${asset.salvage_value} not deducted from depreciation base",
                expected=total_expected,
                actual=total_actual,
                variance=abs(total_actual - total_expected),
                confidence=0.95,
                pattern_id=SelfHealPatternId.AW_004,
                corrected_amount=total_expected,
            ))
            return True
    return False


def _check_method(
    asset: ScenarioAssetRecord,
    actual_schedule: list[DepreciationEntry],
    expected_schedule: list,
    findings: list[DetectionFinding],
) -> bool:
    """Check if the wrong depreciation method was applied.
    Uses statistical pattern detection: SL is constant, DDB/SYD are decreasing."""
    if len(actual_schedule) < 3 or len(expected_schedule) < 3:
        return False

    # Compare actual vs expected for the declared method
    # Use periods 1..N-1 (skip first for convention, skip last for adjustment)
    n = min(len(actual_schedule), len(expected_schedule))
    start = 1
    end = min(n, 10)
    if end - start < 2:
        return False

    actual_amts = [actual_schedule[i].amount for i in range(start, end)]
    expected_amts = [expected_schedule[i].amount for i in range(start, end)]

    # Check if actual matches expected method
    total_deviation = sum(abs(a - e) for a, e in zip(actual_amts, expected_amts))
    avg_expected = sum(expected_amts) / len(expected_amts)
    if avg_expected > 0:
        relative_deviation = total_deviation / (avg_expected * len(actual_amts))
    else:
        return False

    if relative_deviation < Decimal("0.05"):
        # Actual matches declared method within 5% — no method error
        return False

    # Actual doesn't match declared method. Try to identify what method IS being used.
    # Check for SL pattern: constant amounts (low variance)
    actual_is_constant = _is_constant_pattern(actual_amts)
    # Check for declining pattern (DDB/SYD signature)
    actual_is_declining = _is_declining_pattern(actual_amts)

    declared = asset.depreciation_method

    # SL declared but pattern is declining → likely DDB or SYD applied
    if declared == DepreciationMethod.STRAIGHT_LINE and actual_is_declining:
        findings.append(_make_finding(
            error_type=AssetTriggerReason.RECLASSIFICATION_ANOMALY,
            asset_ids=[asset.asset_id],
            description=f"Declared STRAIGHT_LINE but schedule shows declining pattern (likely DDB or SYD)",
            confidence=0.90,
        ))
        return True

    # DDB/SYD declared but pattern is constant → likely SL applied
    if declared in (DepreciationMethod.DOUBLE_DECLINING, DepreciationMethod.SUM_OF_YEARS) and actual_is_constant:
        findings.append(_make_finding(
            error_type=AssetTriggerReason.RECLASSIFICATION_ANOMALY,
            asset_ids=[asset.asset_id],
            description=f"Declared {declared.value} but schedule shows constant pattern (likely STRAIGHT_LINE)",
            confidence=0.90,
        ))
        return True

    # General case: significant deviation from expected but no clear pattern match
    if relative_deviation > Decimal("0.15"):
        findings.append(_make_finding(
            error_type=AssetTriggerReason.DEPRECIATION_VARIANCE_EXCEEDS_THRESHOLD,
            asset_ids=[asset.asset_id],
            description=f"Schedule amounts deviate significantly from {declared.value} calculation",
            confidence=0.80,
        ))
        return True

    return False


def _is_constant_pattern(amounts: list[Decimal]) -> bool:
    """Check if amounts are approximately constant (SL signature)."""
    if len(amounts) < 2:
        return True
    avg = sum(amounts) / len(amounts)
    if avg == 0:
        return True
    max_dev = max(abs(a - avg) for a in amounts)
    return max_dev / avg < Decimal("0.02")


def _is_declining_pattern(amounts: list[Decimal]) -> bool:
    """Check if amounts show a declining trend (DDB/SYD signature)."""
    if len(amounts) < 3:
        return False
    declining_count = sum(1 for i in range(1, len(amounts)) if amounts[i] < amounts[i - 1])
    return declining_count >= len(amounts) * 0.6


def _check_convention(
    asset: ScenarioAssetRecord,
    actual_schedule: list[DepreciationEntry],
    expected_schedule: list,
    findings: list[DetectionFinding],
) -> bool:
    """Check first-period amount matches the declared convention (AW-005)."""
    if not actual_schedule or not expected_schedule:
        return False

    actual_first = actual_schedule[0].amount
    expected_first = expected_schedule[0].amount

    if abs(actual_first - expected_first) <= Decimal("1.00"):
        return False

    # Check if it matches a different convention
    acq_date = _parse_date(asset.acquisition_date)
    for alt_conv in DepreciationConvention:
        if alt_conv == asset.convention:
            continue
        try:
            alt_schedule = calculate_monthly_depreciation(
                cost=asset.cost,
                salvage=asset.salvage_value,
                life_months=asset.useful_life_months,
                method=asset.depreciation_method,
                convention=alt_conv,
                acq_date=acq_date,
            )
        except (NotImplementedError, ValueError):
            continue
        if alt_schedule and abs(actual_first - alt_schedule[0].amount) < Decimal("1.00"):
            findings.append(_make_finding(
                error_type=AssetTriggerReason.DEPRECIATION_VARIANCE_EXCEEDS_THRESHOLD,
                asset_ids=[asset.asset_id],
                description=f"First-period convention appears to be {alt_conv.value} instead of declared {asset.convention.value}",
                expected=expected_first,
                actual=actual_first,
                variance=abs(actual_first - expected_first),
                confidence=0.90,
                pattern_id=SelfHealPatternId.AW_005,
                corrected_amount=expected_first,
            ))
            return True

    # No convention match but still a big first-period discrepancy
    findings.append(_make_finding(
        error_type=AssetTriggerReason.DEPRECIATION_VARIANCE_EXCEEDS_THRESHOLD,
        asset_ids=[asset.asset_id],
        description=f"First-period amount ${actual_first} differs from expected ${expected_first}",
        expected=expected_first,
        actual=actual_first,
        variance=abs(actual_first - expected_first),
        confidence=0.80,
        pattern_id=SelfHealPatternId.AW_005,
    ))
    return True


def _check_missing_periods(
    asset: ScenarioAssetRecord,
    actual_schedule: list[DepreciationEntry],
    expected_schedule: list,
    findings: list[DetectionFinding],
) -> bool:
    """Detect gaps in the depreciation schedule and duplicate entries (AW-002)."""
    found = False

    if not actual_schedule:
        if expected_schedule and asset.status in (AssetStatus.ACTIVE, AssetStatus.IMPAIRED):
            findings.append(_make_finding(
                error_type=AssetTriggerReason.MISSING_DEPRECIATION_ENTRY,
                asset_ids=[asset.asset_id],
                description="No depreciation entries found for active asset",
                confidence=0.95,
                pattern_id=SelfHealPatternId.AW_002,
            ))
            return True
        return False

    actual_periods = {e.period for e in actual_schedule}
    expected_periods = {e.period for e in expected_schedule}
    missing = expected_periods - actual_periods

    if missing:
        findings.append(_make_finding(
            error_type=AssetTriggerReason.MISSING_DEPRECIATION_ENTRY,
            asset_ids=[asset.asset_id],
            description=f"Missing depreciation entries for periods: {', '.join(sorted(missing))}",
            confidence=0.95,
            pattern_id=SelfHealPatternId.AW_002,
        ))
        found = True

    # Check for duplicate periods
    period_counts: dict[str, int] = {}
    for e in actual_schedule:
        period_counts[e.period] = period_counts.get(e.period, 0) + 1
    duplicates = [p for p, c in period_counts.items() if c > 1]
    if duplicates:
        findings.append(_make_finding(
            error_type=AssetTriggerReason.DEPRECIATION_VARIANCE_EXCEEDS_THRESHOLD,
            asset_ids=[asset.asset_id],
            description=f"Duplicate depreciation entries for periods: {', '.join(sorted(duplicates))}",
            confidence=0.98,
            pattern_id=SelfHealPatternId.AW_001,
        ))
        found = True

    return found


def _check_useful_life(
    asset: ScenarioAssetRecord,
    actual_schedule: list[DepreciationEntry],
    expected_schedule: list,
    findings: list[DetectionFinding],
) -> bool:
    """Compare implied useful life from schedule length vs declared (AW-003).

    Only flags if the schedule appears to be complete (not a partial window).
    A schedule is considered complete if it covers >= 70% of declared life
    or exceeds declared life.
    """
    if not actual_schedule or len(actual_schedule) < 2:
        return False

    actual_months = len(actual_schedule)
    declared_months = asset.useful_life_months
    diff = abs(actual_months - declared_months)

    if diff <= 6:
        return False

    # Only flag if schedule appears complete (not a partial data window)
    # Over-depreciating: schedule longer than declared
    is_over = actual_months > declared_months + 6
    # Schedule covers most of declared life (>= 70%) but ends early/late
    is_mostly_complete = actual_months >= declared_months * 0.7
    # Schedule's total depreciation is close to depreciable base
    depreciable_base = asset.cost - asset.salvage_value
    total_actual = sum(e.amount for e in actual_schedule)
    is_fully_depreciated = depreciable_base > 0 and total_actual >= depreciable_base * Decimal("0.7")

    if is_over or is_mostly_complete or is_fully_depreciated:
        findings.append(_make_finding(
            error_type=AssetTriggerReason.USEFUL_LIFE_MISMATCH,
            asset_ids=[asset.asset_id],
            description=f"Implied useful life ({actual_months} months) differs from declared ({declared_months} months)",
            expected=Decimal(str(declared_months)),
            actual=Decimal(str(actual_months)),
            variance=Decimal(str(diff)),
            confidence=0.90,
            pattern_id=SelfHealPatternId.AW_003,
        ))
        return True
    return False


def _check_rounding(
    asset: ScenarioAssetRecord,
    actual_schedule: list[DepreciationEntry],
    expected_schedule: list,
    findings: list[DetectionFinding],
) -> bool:
    """Check for accumulated rounding/amount errors (AW-001)."""
    if len(actual_schedule) < 2 or len(expected_schedule) < 2:
        return False

    total_actual = sum(e.amount for e in actual_schedule)
    total_expected = sum(e.amount for e in expected_schedule)
    depreciable_base = asset.cost - asset.salvage_value

    actual_diff = abs(total_actual - depreciable_base)
    # Compare to what's expected for same number of periods
    expected_for_same = sum(e.amount for e in expected_schedule[:len(actual_schedule)])
    period_diff = abs(total_actual - expected_for_same)

    if period_diff > Decimal("5.00"):
        findings.append(_make_finding(
            error_type=AssetTriggerReason.DEPRECIATION_VARIANCE_EXCEEDS_THRESHOLD,
            asset_ids=[asset.asset_id],
            description=f"Total depreciation ${total_actual} differs from expected ${expected_for_same} over {len(actual_schedule)} periods",
            expected=expected_for_same,
            actual=total_actual,
            variance=period_diff,
            confidence=0.85,
            pattern_id=SelfHealPatternId.AW_001,
            corrected_amount=expected_for_same,
        ))
        return True
    return False


def _check_lifecycle(
    asset: ScenarioAssetRecord,
    actual_schedule: list[DepreciationEntry],
    findings: list[DetectionFinding],
    flagged: set[str],
) -> None:
    """Check lifecycle consistency."""
    # Disposed asset still depreciating
    if asset.status == AssetStatus.DISPOSED and asset.disposal_date:
        disposal_date = _parse_date(asset.disposal_date)
        disposal_period = f"{disposal_date.year:04d}-{disposal_date.month:02d}"
        post_disposal = [e for e in actual_schedule if e.period > disposal_period]
        if post_disposal:
            findings.append(_make_finding(
                error_type=AssetTriggerReason.DISPOSAL_WITHOUT_RETIREMENT,
                asset_ids=[asset.asset_id],
                description=f"Asset disposed on {asset.disposal_date} but has {len(post_disposal)} entries after disposal",
                confidence=0.98,
            ))
            flagged.add(asset.asset_id)

    # Disposed without disposal_date
    if asset.status == AssetStatus.DISPOSED and not asset.disposal_date:
        findings.append(_make_finding(
            error_type=AssetTriggerReason.DISPOSAL_WITHOUT_RETIREMENT,
            asset_ids=[asset.asset_id],
            description="Asset marked as disposed but no disposal date recorded",
            confidence=0.95,
        ))
        flagged.add(asset.asset_id)

    # Active but disposal_date set
    if asset.status == AssetStatus.ACTIVE and asset.disposal_date:
        findings.append(_make_finding(
            error_type=AssetTriggerReason.DISPOSAL_WITHOUT_RETIREMENT,
            asset_ids=[asset.asset_id],
            description="Asset is active but has a disposal date set",
            confidence=0.90,
        ))
        flagged.add(asset.asset_id)

    # Fully depreciated with nonzero NBV
    if asset.status == AssetStatus.FULLY_DEPRECIATED and actual_schedule:
        last_nbv = actual_schedule[-1].net_book_value
        if last_nbv > asset.salvage_value + Decimal("1.00"):
            findings.append(_make_finding(
                error_type=AssetTriggerReason.IMPAIRMENT_INDICATOR_DETECTED,
                asset_ids=[asset.asset_id],
                description=f"Fully depreciated asset has NBV ${last_nbv} above salvage ${asset.salvage_value}",
                expected=asset.salvage_value,
                actual=last_nbv,
                variance=last_nbv - asset.salvage_value,
                confidence=0.95,
            ))
            flagged.add(asset.asset_id)


def _check_gl_balances(
    asset_register: list[ScenarioAssetRecord],
    depreciation_schedule: list[DepreciationEntry],
    gl_balances: list[GLBalance],
    findings: list[DetectionFinding],
) -> None:
    """Check GL balances match depreciation schedule totals."""
    if not gl_balances:
        return

    asset_entity_map: dict[str, str] = {a.asset_id: a.entity_id for a in asset_register}
    entity_period_totals: dict[str, Decimal] = {}
    for entry in depreciation_schedule:
        entity = asset_entity_map.get(entry.asset_id, "ENTITY-001")
        key = f"{entity}:{entry.period}"
        entity_period_totals[key] = entity_period_totals.get(key, Decimal("0")) + entry.amount

    for gl in gl_balances:
        key = f"{gl.entity_id}:{gl.period}"
        schedule_total = entity_period_totals.get(key, Decimal("0"))
        if abs(gl.balance - schedule_total) > Decimal("1.00"):
            affected_assets = [a.asset_id for a in asset_register if a.entity_id == gl.entity_id]
            findings.append(_make_finding(
                error_type=AssetTriggerReason.DEPRECIATION_VARIANCE_EXCEEDS_THRESHOLD,
                asset_ids=affected_assets,
                description=f"GL balance ${gl.balance} for {gl.account_code} period {gl.period} differs from schedule total ${schedule_total}",
                expected=schedule_total,
                actual=gl.balance,
                variance=abs(gl.balance - schedule_total),
                confidence=0.85,
            ))


def _check_duplicate_entries(
    asset_register: list[ScenarioAssetRecord],
    depreciation_schedule: list[DepreciationEntry],
    findings: list[DetectionFinding],
) -> None:
    """Check for same asset claimed by multiple entities."""
    all_asset_ids: dict[str, list[str]] = {}
    for asset in asset_register:
        all_asset_ids.setdefault(asset.asset_id, []).append(asset.entity_id)

    for asset_id, entities in all_asset_ids.items():
        if len(set(entities)) > 1:
            findings.append(_make_finding(
                error_type=AssetTriggerReason.RECLASSIFICATION_ANOMALY,
                asset_ids=[asset_id],
                description=f"Asset {asset_id} claimed by multiple entities: {', '.join(set(entities))}",
                confidence=0.95,
            ))
