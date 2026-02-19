"""Tests for ingest validator."""

from decimal import Decimal

from sentient_ledger.ingest.validator import (
    validate_depreciation_entries,
    validate_fixed_asset_records,
    validate_trial_balance_records,
)


def _valid_tb_record(**overrides) -> dict:
    rec = {
        "record_id": "rec-001",
        "account": {"code": "110100", "name": "Cash", "category": "ASSET"},
        "balances": {
            "opening": Decimal("100000"),
            "debits": Decimal("50000"),
            "credits": Decimal("30000"),
            "closing": Decimal("120000"),
            "movement": Decimal("20000"),
        },
        "currency": {"transaction": "USD", "reporting": "USD"},
        "period": {"fiscal_year": 2026, "fiscal_period": 1, "calendar_month": "2026-01"},
        "integrity": {"source_row_hash": "abc123", "balance_verified": True},
    }
    rec.update(overrides)
    return rec


def _valid_fa_record(**overrides) -> dict:
    rec = {
        "record_id": "fa-001",
        "identity": {"asset_id": "FA-001", "group": "MACHINERY", "description": "CNC"},
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
        },
        "integrity": {"source_row_hash": "def456"},
    }
    rec.update(overrides)
    return rec


class TestValidateTrialBalance:
    def test_valid_record_passes(self):
        result = validate_trial_balance_records([_valid_tb_record()])
        assert len(result.valid_records) == 1
        assert result.error_count == 0

    def test_negative_debits_excluded(self):
        rec = _valid_tb_record()
        rec["balances"]["debits"] = Decimal("-100")
        result = validate_trial_balance_records([rec])
        assert len(result.valid_records) == 0
        assert result.error_count == 1

    def test_negative_credits_excluded(self):
        rec = _valid_tb_record()
        rec["balances"]["credits"] = Decimal("-50")
        result = validate_trial_balance_records([rec])
        assert len(result.valid_records) == 0
        assert result.error_count == 1

    def test_short_account_code_warning_still_passes(self):
        rec = _valid_tb_record()
        rec["account"]["code"] = "10"
        result = validate_trial_balance_records([rec])
        assert len(result.valid_records) == 1  # WARNING doesn't exclude
        assert result.warning_count == 1

    def test_unsupported_currency_excluded(self):
        rec = _valid_tb_record()
        rec["currency"]["transaction"] = "XYZ"
        result = validate_trial_balance_records([rec])
        assert len(result.valid_records) == 0
        assert result.error_count == 1


class TestValidateFixedAssets:
    def test_valid_record_passes(self):
        result = validate_fixed_asset_records([_valid_fa_record()])
        assert len(result.valid_records) == 1
        assert result.error_count == 0

    def test_zero_cost_excluded(self):
        rec = _valid_fa_record()
        rec["acquisition"]["cost"] = Decimal("0")
        result = validate_fixed_asset_records([rec])
        assert len(result.valid_records) == 0

    def test_negative_salvage_excluded(self):
        rec = _valid_fa_record()
        rec["acquisition"]["salvage_value"] = Decimal("-1000")
        result = validate_fixed_asset_records([rec])
        assert len(result.valid_records) == 0

    def test_salvage_exceeds_cost_excluded(self):
        rec = _valid_fa_record()
        rec["acquisition"]["salvage_value"] = Decimal("600000")
        result = validate_fixed_asset_records([rec])
        assert len(result.valid_records) == 0

    def test_zero_useful_life_excluded(self):
        rec = _valid_fa_record()
        rec["acquisition"]["useful_life_months"] = 0
        result = validate_fixed_asset_records([rec])
        assert len(result.valid_records) == 0

    def test_negative_nbv_warning_still_passes(self):
        rec = _valid_fa_record()
        rec["current_state"]["net_book_value"] = Decimal("-100")
        result = validate_fixed_asset_records([rec])
        assert len(result.valid_records) == 1
        assert result.warning_count == 1

    def test_multiple_records_mixed(self):
        good = _valid_fa_record()
        bad = _valid_fa_record()
        bad["acquisition"]["cost"] = Decimal("0")
        result = validate_fixed_asset_records([good, bad])
        assert len(result.valid_records) == 1
        assert result.error_count >= 1


def _valid_ds_record(**overrides) -> dict:
    rec = {
        "asset_id": "FA-001",
        "period": "2024-01",
        "amount": Decimal("3750"),
        "accumulated": Decimal("3750"),
        "net_book_value": Decimal("446250"),
    }
    rec.update(overrides)
    return rec


class TestValidateDepreciationEntries:
    def test_valid_record_passes(self):
        result = validate_depreciation_entries([_valid_ds_record()])
        assert len(result.valid_records) == 1
        assert result.error_count == 0

    def test_negative_amount_excluded(self):
        rec = _valid_ds_record(amount=Decimal("-100"))
        result = validate_depreciation_entries([rec])
        assert len(result.valid_records) == 0
        assert result.error_count == 1

    def test_negative_accumulated_excluded(self):
        rec = _valid_ds_record(accumulated=Decimal("-500"))
        result = validate_depreciation_entries([rec])
        assert len(result.valid_records) == 0
        assert result.error_count == 1

    def test_negative_nbv_warning_still_passes(self):
        rec = _valid_ds_record(net_book_value=Decimal("-100"))
        result = validate_depreciation_entries([rec])
        assert len(result.valid_records) == 1
        assert result.warning_count == 1

    def test_invalid_period_format_excluded(self):
        rec = _valid_ds_record(period="2024-13")
        result = validate_depreciation_entries([rec])
        assert len(result.valid_records) == 0
        assert result.error_count == 1
