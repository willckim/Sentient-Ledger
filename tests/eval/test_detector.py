"""Unit tests for the error detector."""

from datetime import date
from decimal import Decimal

import pytest

from sentient_ledger.engine.detector import detect_errors
from sentient_ledger.models.enums import (
    AssetStatus,
    AssetTriggerReason,
    DepreciationConvention,
    DepreciationMethod,
)
from sentient_ledger.models.eval import (
    DepreciationEntry,
    GLBalance,
    ScenarioAssetRecord,
)


def _make_asset(**kwargs) -> ScenarioAssetRecord:
    defaults = dict(
        asset_id="A-001",
        acquisition_date="2024-01-01",
        cost=Decimal("120000"),
        salvage_value=Decimal("0"),
        useful_life_months=120,
        depreciation_method=DepreciationMethod.STRAIGHT_LINE,
        convention=DepreciationConvention.FULL_MONTH,
        status=AssetStatus.ACTIVE,
    )
    defaults.update(kwargs)
    return ScenarioAssetRecord(**defaults)


def _make_schedule(asset_id: str, periods: list[tuple[str, str]]) -> list[DepreciationEntry]:
    """Build schedule from list of (period, amount) tuples."""
    entries = []
    acc = Decimal("0")
    cost = Decimal("120000")
    for period, amount in periods:
        amt = Decimal(amount)
        acc += amt
        entries.append(DepreciationEntry(
            asset_id=asset_id,
            period=period,
            amount=amt,
            accumulated=acc,
            net_book_value=cost - acc,
        ))
    return entries


class TestSalvageValueCheck:
    def test_detects_salvage_not_deducted(self):
        """Should detect when depreciation base uses cost instead of cost-salvage."""
        asset = _make_asset(
            cost=Decimal("100000"),
            salvage_value=Decimal("10000"),
            useful_life_months=60,
        )
        # Wrong: using $100,000/60 = $1,666.67 instead of $90,000/60 = $1,500
        schedule = _make_schedule("A-001", [
            (f"2024-{m:02d}", "1666.67") for m in range(1, 13)
        ])
        # Fix NBV based on actual cost
        for e in schedule:
            e.net_book_value = asset.cost - e.accumulated

        result = detect_errors([asset], [], schedule)
        salvage_findings = [f for f in result.findings
                          if "salvage" in f.description.lower() or "AW-004" == (f.pattern_id.value if f.pattern_id else "")]
        assert len(salvage_findings) >= 1


class TestMissingPeriods:
    def test_detects_missing_period(self):
        """Should detect gaps in schedule."""
        asset = _make_asset()
        # Missing 2024-06
        periods = [(f"2024-{m:02d}", "1000.00") for m in range(1, 13) if m != 6]
        schedule = _make_schedule("A-001", periods)

        result = detect_errors([asset], [], schedule)
        missing = [f for f in result.findings
                  if f.error_type == AssetTriggerReason.MISSING_DEPRECIATION_ENTRY]
        assert len(missing) >= 1

    def test_detects_duplicate_period(self):
        """Should detect duplicate entries for same period."""
        asset = _make_asset()
        periods = [(f"2024-{m:02d}", "1000.00") for m in range(1, 13)]
        periods.append(("2024-03", "1000.00"))  # duplicate
        schedule = _make_schedule("A-001", periods)

        result = detect_errors([asset], [], schedule)
        dup_findings = [f for f in result.findings
                       if "duplicate" in f.description.lower()]
        assert len(dup_findings) >= 1


class TestUsefulLife:
    def test_detects_life_mismatch(self):
        """Should detect when schedule is longer than declared life with correct amounts."""
        # 60,000 over 60 months = $1,000/mo. But schedule has 80 entries at $1,000.
        asset = _make_asset(
            cost=Decimal("60000"),
            salvage_value=Decimal("0"),
            useful_life_months=60,
        )
        # Schedule with 80 entries at correct per-period amount but more periods than declared
        periods = []
        for y in range(2024, 2031):
            for m in range(1, 13):
                periods.append((f"{y}-{m:02d}", "1000.00"))
                if len(periods) >= 80:
                    break
            if len(periods) >= 80:
                break
        schedule = _make_schedule("A-001", periods)

        result = detect_errors([asset], [], schedule)
        # May detect as useful_life mismatch or rounding variance
        assert result.errors_detected >= 1


class TestLifecycle:
    def test_disposed_still_depreciating(self):
        """Should detect entries after disposal date."""
        asset = _make_asset(
            status=AssetStatus.DISPOSED,
            disposal_date="2024-06-15",
        )
        periods = [(f"2024-{m:02d}", "1000.00") for m in range(1, 13)]
        schedule = _make_schedule("A-001", periods)

        result = detect_errors([asset], [], schedule)
        disposal_findings = [f for f in result.findings
                           if f.error_type == AssetTriggerReason.DISPOSAL_WITHOUT_RETIREMENT]
        assert len(disposal_findings) >= 1

    def test_disposed_without_date(self):
        """Should detect disposed asset with no disposal date."""
        asset = _make_asset(
            status=AssetStatus.DISPOSED,
            disposal_date=None,
        )
        schedule = _make_schedule("A-001", [
            (f"2024-{m:02d}", "1000.00") for m in range(1, 13)
        ])

        result = detect_errors([asset], [], schedule)
        findings = [f for f in result.findings
                   if f.error_type == AssetTriggerReason.DISPOSAL_WITHOUT_RETIREMENT]
        assert len(findings) >= 1

    def test_fully_depreciated_nonzero_nbv(self):
        """Should detect fully depreciated asset with NBV above salvage."""
        asset = _make_asset(
            cost=Decimal("60000"),
            salvage_value=Decimal("0"),
            useful_life_months=60,
            status=AssetStatus.FULLY_DEPRECIATED,
        )
        # Under-depreciated: only $40,000 of $60,000
        schedule = _make_schedule("A-001", [
            (f"2024-{m:02d}", "666.67") for m in range(1, 13)
        ])
        for entry in schedule:
            entry.net_book_value = asset.cost - entry.accumulated

        result = detect_errors([asset], [], schedule)
        nbv_findings = [f for f in result.findings
                       if f.error_type == AssetTriggerReason.IMPAIRMENT_INDICATOR_DETECTED]
        assert len(nbv_findings) >= 1


class TestGLBalance:
    def test_gl_mismatch(self):
        """Should detect GL balance not matching schedule total."""
        asset = _make_asset()
        schedule = _make_schedule("A-001", [
            (f"2024-{m:02d}", "1000.00") for m in range(1, 13)
        ])
        gl = [GLBalance(
            account_code="5100",
            account_name="Depreciation Expense",
            period="2024-12",
            balance=Decimal("15000"),  # Should be 1000 for one month
            entity_id="ENTITY-001",
        )]

        result = detect_errors([asset], gl, schedule)
        gl_findings = [f for f in result.findings
                      if "GL" in f.description or "gl" in f.description.lower()]
        assert len(gl_findings) >= 1


class TestMultiEntity:
    def test_asset_in_multiple_entities(self):
        """Should detect same asset claimed by multiple entities."""
        asset1 = _make_asset(entity_id="ENTITY-001")
        asset2 = _make_asset(entity_id="ENTITY-002")
        schedule = _make_schedule("A-001", [
            (f"2024-{m:02d}", "1000.00") for m in range(1, 13)
        ])

        result = detect_errors([asset1, asset2], [], schedule)
        multi_findings = [f for f in result.findings
                         if f.error_type == AssetTriggerReason.RECLASSIFICATION_ANOMALY
                         and "multiple entities" in f.description.lower()]
        assert len(multi_findings) >= 1


class TestCleanData:
    def test_no_errors_on_clean_data(self):
        """Clean data should produce no findings."""
        asset = _make_asset()
        # Correct schedule: $120,000 / 120 months = $1,000/mo
        periods = []
        for y in range(2024, 2034):
            for m in range(1, 13):
                periods.append((f"{y}-{m:02d}", "1000.00"))
                if len(periods) >= 120:
                    break
            if len(periods) >= 120:
                break
        schedule = _make_schedule("A-001", periods)

        result = detect_errors([asset], [], schedule)
        assert result.errors_detected == 0, (
            f"Expected 0 errors, got {result.errors_detected}: "
            f"{[f.description for f in result.findings]}"
        )
