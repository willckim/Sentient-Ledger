"""Tests for ingest column mapper."""

from decimal import Decimal

from sentient_ledger.ingest.mapper import (
    map_depreciation_entry_row,
    map_fixed_asset_row,
    map_trial_balance_row,
)


def _clean_tb_row() -> dict:
    """A valid D365 trial balance row."""
    return {
        "MainAccount": "110100",
        "AccountName": "Cash - Operating",
        "BusinessUnit": "BU-001",
        "Department": "FIN",
        "CostCenter": "CC-100",
        "OpeningBalance": "100000.00",
        "Debits": "50000.00",
        "Credits": "30000.00",
        "ClosingBalance": "120000.00",
        "TransactionCurrency": "USD",
        "ReportingCurrency": "USD",
        "ExchangeRate": "1.00",
        "CalendarMonth": "2026-01",
    }


def _clean_fa_row() -> dict:
    """A valid D365 fixed asset row."""
    return {
        "AssetId": "FA-001",
        "AssetGroup": "MACHINERY",
        "Description": "CNC Machine",
        "AcquisitionDate": "2024-01-15",
        "AcquisitionCost": "500000.00",
        "DepreciationMethod": "StraightLine",
        "ServiceLife": "10",
        "ServiceLifeUnit": "Years",
        "SalvageValue": "50000.00",
        "Convention": "HalfMonth",
        "AccumulatedDepreciation": "90000.00",
        "NetBookValue": "410000.00",
        "Status": "Open",
    }


class TestMapTrialBalanceRow:
    def test_clean_row_maps_successfully(self):
        result = map_trial_balance_row(_clean_tb_row(), ingestion_id="ING-001")
        assert result.record is not None
        assert result.errors == []
        assert result.record["source"] == "DYNAMICS_365"
        assert result.record["ingestion_id"] == "ING-001"

    def test_account_category_heuristic(self):
        row = _clean_tb_row()
        result = map_trial_balance_row(row)
        assert result.record["account"]["category"] == "ASSET"  # starts with 1

        row["MainAccount"] = "200100"
        result = map_trial_balance_row(row)
        assert result.record["account"]["category"] == "LIABILITY"

        row["MainAccount"] = "400100"
        result = map_trial_balance_row(row)
        assert result.record["account"]["category"] == "REVENUE"

        row["MainAccount"] = "500100"
        result = map_trial_balance_row(row)
        assert result.record["account"]["category"] == "EXPENSE"

    def test_movement_computed(self):
        result = map_trial_balance_row(_clean_tb_row())
        bal = result.record["balances"]
        assert bal["movement"] == Decimal("50000.00") - Decimal("30000.00")

    def test_balance_verified(self):
        result = map_trial_balance_row(_clean_tb_row())
        assert result.record["integrity"]["balance_verified"] is True

    def test_fiscal_year_period_from_calendar_month(self):
        result = map_trial_balance_row(_clean_tb_row())
        assert result.record["period"]["fiscal_year"] == 2026
        assert result.record["period"]["fiscal_period"] == 1

    def test_source_row_hash_populated(self):
        result = map_trial_balance_row(_clean_tb_row())
        assert len(result.record["integrity"]["source_row_hash"]) == 64  # SHA-256

    def test_missing_required_column_errors(self):
        row = _clean_tb_row()
        del row["MainAccount"]
        result = map_trial_balance_row(row)
        assert result.record is None
        assert len(result.errors) > 0

    def test_empty_required_value_errors(self):
        row = _clean_tb_row()
        row["MainAccount"] = ""
        result = map_trial_balance_row(row)
        assert result.record is None
        assert any("empty" in e.lower() for e in result.errors)

    def test_invalid_decimal_errors(self):
        row = _clean_tb_row()
        row["Debits"] = "not-a-number"
        result = map_trial_balance_row(row)
        assert result.record is None
        assert any("decimal" in e.lower() for e in result.errors)


class TestMapFixedAssetRow:
    def test_clean_row_maps_successfully(self):
        result = map_fixed_asset_row(_clean_fa_row(), ingestion_id="ING-002")
        assert result.record is not None
        assert result.errors == []
        assert result.record["identity"]["asset_id"] == "FA-001"
        assert result.record["ingestion_id"] == "ING-002"

    def test_enum_translation_method(self):
        result = map_fixed_asset_row(_clean_fa_row())
        assert result.record["acquisition"]["method"] == "STRAIGHT_LINE"

    def test_enum_translation_convention(self):
        result = map_fixed_asset_row(_clean_fa_row())
        assert result.record["acquisition"]["convention"] == "HALF_MONTH"

    def test_enum_translation_status(self):
        result = map_fixed_asset_row(_clean_fa_row())
        assert result.record["current_state"]["status"] == "ACTIVE"

    def test_service_life_years_to_months(self):
        result = map_fixed_asset_row(_clean_fa_row())
        assert result.record["acquisition"]["useful_life_months"] == 120  # 10 * 12

    def test_depreciable_base_computed(self):
        result = map_fixed_asset_row(_clean_fa_row())
        assert result.record["acquisition"]["depreciable_base"] == Decimal("450000.00")

    def test_nbv_verified_computed(self):
        result = map_fixed_asset_row(_clean_fa_row())
        # 500000 - 90000 == 410000 => True
        assert result.record["current_state"]["nbv_verified"] is True

    def test_unknown_method_errors(self):
        row = _clean_fa_row()
        row["DepreciationMethod"] = "MagicMethod"
        result = map_fixed_asset_row(row)
        assert result.record is None
        assert any("unknown depreciation method" in e.lower() for e in result.errors)

    def test_unknown_status_errors(self):
        row = _clean_fa_row()
        row["Status"] = "Archived"
        result = map_fixed_asset_row(row)
        assert result.record is None
        assert any("unknown asset status" in e.lower() for e in result.errors)

    def test_source_row_hash_populated(self):
        result = map_fixed_asset_row(_clean_fa_row())
        assert len(result.record["integrity"]["source_row_hash"]) == 64


def _clean_ds_row() -> dict:
    """A valid D365 depreciation schedule row."""
    return {
        "AssetId": "FA-001",
        "Period": "2024-01",
        "DepreciationAmount": "3750.00",
        "AccumulatedDepreciation": "3750.00",
        "NetBookValue": "446250.00",
    }


class TestMapDepreciationEntryRow:
    def test_clean_row_maps_successfully(self):
        result = map_depreciation_entry_row(_clean_ds_row())
        assert result.record is not None
        assert result.errors == []
        assert result.record["asset_id"] == "FA-001"
        assert result.record["period"] == "2024-01"

    def test_decimal_coercion(self):
        result = map_depreciation_entry_row(_clean_ds_row())
        assert result.record["amount"] == Decimal("3750.00")
        assert result.record["accumulated"] == Decimal("3750.00")
        assert result.record["net_book_value"] == Decimal("446250.00")

    def test_missing_required_column_errors(self):
        row = _clean_ds_row()
        del row["AssetId"]
        result = map_depreciation_entry_row(row)
        assert result.record is None
        assert len(result.errors) > 0

    def test_invalid_period_format_errors(self):
        row = _clean_ds_row()
        row["Period"] = "Jan-2024"
        result = map_depreciation_entry_row(row)
        assert result.record is None
        assert any("period format" in e.lower() for e in result.errors)

    def test_invalid_decimal_errors(self):
        row = _clean_ds_row()
        row["DepreciationAmount"] = "abc"
        result = map_depreciation_entry_row(row)
        assert result.record is None
        assert any("decimal" in e.lower() for e in result.errors)
