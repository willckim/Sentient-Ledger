"""Tests for ingest adapter — canonical → detector format conversion."""

from decimal import Decimal

from sentient_ledger.ingest.adapter import (
    adapt_state_for_detector,
    canonical_asset_to_detector,
    is_canonical_format,
    tb_records_to_gl_balances,
)


def _canonical_fa_record() -> dict:
    """A canonical FA record as produced by map_fixed_asset_row."""
    return {
        "record_id": "rec-001",
        "source": "DYNAMICS_365",
        "ingestion_id": "ING-001",
        "identity": {
            "asset_id": "FA-001",
            "group": "MACHINERY",
            "description": "CNC Machine",
        },
        "acquisition": {
            "date": "2024-01-15",
            "cost": Decimal("500000"),
            "method": "STRAIGHT_LINE",
            "useful_life_months": 120,
            "salvage_value": Decimal("50000"),
            "depreciable_base": Decimal("450000"),
            "convention": "HALF_MONTH",
        },
        "current_state": {
            "accumulated_depreciation": Decimal("90000"),
            "net_book_value": Decimal("410000"),
            "nbv_verified": True,
            "status": "ACTIVE",
            "last_depreciation_date": None,
            "remaining_life_months": 96,
        },
        "integrity": {"source_row_hash": "abc123"},
    }


def _flat_asset_record() -> dict:
    """A flat ScenarioAssetRecord dict as used by eval tests."""
    return {
        "asset_id": "FA-001",
        "description": "CNC Machine",
        "acquisition_date": "2024-01-15",
        "cost": Decimal("500000"),
        "salvage_value": Decimal("50000"),
        "useful_life_months": 120,
        "depreciation_method": "STRAIGHT_LINE",
        "convention": "HALF_MONTH",
        "status": "ACTIVE",
        "entity_id": "ENTITY-001",
        "group": "PP&E",
    }


def _canonical_tb_record() -> dict:
    """A canonical TB record as produced by map_trial_balance_row."""
    return {
        "record_id": "rec-tb-001",
        "account": {"code": "110100", "name": "Cash - Operating", "category": "ASSET"},
        "dimensions": {
            "business_unit": "BU-001",
            "department": "FIN",
            "cost_center": "CC-100",
            "composite_key": "110100-BU-001",
        },
        "balances": {
            "opening": Decimal("100000"),
            "debits": Decimal("50000"),
            "credits": Decimal("30000"),
            "closing": Decimal("120000"),
            "movement": Decimal("20000"),
        },
        "currency": {"transaction": "USD", "reporting": "USD"},
        "period": {"fiscal_year": 2026, "fiscal_period": 1, "calendar_month": "2026-01"},
        "integrity": {"source_row_hash": "xyz789", "balance_verified": True},
    }


class TestCanonicalAssetToDetector:
    def test_converts_nested_to_flat(self):
        flat = canonical_asset_to_detector(_canonical_fa_record())
        assert flat["asset_id"] == "FA-001"
        assert flat["acquisition_date"] == "2024-01-15"
        assert flat["depreciation_method"] == "STRAIGHT_LINE"
        assert flat["convention"] == "HALF_MONTH"
        assert flat["status"] == "ACTIVE"

    def test_preserves_decimals(self):
        flat = canonical_asset_to_detector(_canonical_fa_record())
        assert isinstance(flat["cost"], Decimal)
        assert flat["cost"] == Decimal("500000")
        assert flat["salvage_value"] == Decimal("50000")

    def test_maps_group(self):
        flat = canonical_asset_to_detector(_canonical_fa_record())
        assert flat["group"] == "MACHINERY"

    def test_defaults_entity_id(self):
        flat = canonical_asset_to_detector(_canonical_fa_record())
        assert flat["entity_id"] == "ENTITY-001"

    def test_defaults_disposal_fields(self):
        flat = canonical_asset_to_detector(_canonical_fa_record())
        assert flat["disposal_date"] is None
        assert flat["disposal_proceeds"] is None


class TestTbRecordsToGlBalances:
    def test_single_record(self):
        gl = tb_records_to_gl_balances([_canonical_tb_record()])
        assert len(gl) == 1
        assert gl[0]["account_code"] == "110100"
        assert gl[0]["account_name"] == "Cash - Operating"
        assert gl[0]["period"] == "2026-01"
        assert gl[0]["balance"] == Decimal("120000")

    def test_uses_business_unit_as_entity_id(self):
        gl = tb_records_to_gl_balances([_canonical_tb_record()])
        assert gl[0]["entity_id"] == "BU-001"

    def test_preserves_decimal(self):
        gl = tb_records_to_gl_balances([_canonical_tb_record()])
        assert isinstance(gl[0]["balance"], Decimal)

    def test_multiple_records(self):
        rec1 = _canonical_tb_record()
        rec2 = _canonical_tb_record()
        rec2["account"]["code"] = "200100"
        rec2["balances"]["closing"] = Decimal("65000")
        gl = tb_records_to_gl_balances([rec1, rec2])
        assert len(gl) == 2
        assert gl[1]["account_code"] == "200100"
        assert gl[1]["balance"] == Decimal("65000")


class TestIsCanonicalFormat:
    def test_nested_detected(self):
        assert is_canonical_format(_canonical_fa_record()) is True

    def test_flat_detected(self):
        assert is_canonical_format(_flat_asset_record()) is False


class TestAdaptStateForDetector:
    def test_full_conversion_flow(self):
        state = {
            "asset_register": [_canonical_fa_record()],
            "trial_balance_records": [_canonical_tb_record()],
            "depreciation_schedule": [
                {"asset_id": "FA-001", "period": "2024-01", "amount": Decimal("1875"),
                 "accumulated": Decimal("1875"), "net_book_value": Decimal("498125")}
            ],
            "total_rows": 10,
            "malformed_rows": 0,
            "malformed_pct": 0.0,
        }
        adapted = adapt_state_for_detector(state)

        # asset_register should be flattened
        assert adapted["asset_register"][0]["asset_id"] == "FA-001"
        assert "identity" not in adapted["asset_register"][0]

        # gl_balances should be derived
        assert len(adapted["gl_balances"]) == 1
        assert adapted["gl_balances"][0]["account_code"] == "110100"

        # depreciation_schedule passes through
        assert len(adapted["depreciation_schedule"]) == 1
        assert adapted["depreciation_schedule"][0]["asset_id"] == "FA-001"

    def test_flat_records_pass_through(self):
        state = {
            "asset_register": [_flat_asset_record()],
            "trial_balance_records": [],
            "depreciation_schedule": [],
        }
        adapted = adapt_state_for_detector(state)
        # Flat records should not be modified
        assert adapted["asset_register"][0]["asset_id"] == "FA-001"
        assert "identity" not in adapted["asset_register"][0]
