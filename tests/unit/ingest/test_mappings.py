"""Tests for ingest mappings — column maps, enum maps, validation rules."""

from sentient_ledger.ingest.mappings import (
    ASSET_STATUS_MAP,
    DEPRECIATION_CONVENTION_MAP,
    DEPRECIATION_METHOD_MAP,
    DS_COLUMN_MAP,
    DS_REQUIRED_COLUMNS,
    DS_VALIDATIONS,
    FA_COLUMN_MAP,
    FA_REQUIRED_COLUMNS,
    SUPPORTED_CURRENCIES,
    TB_COLUMN_MAP,
    TB_REQUIRED_COLUMNS,
    TB_VALIDATIONS,
    FA_VALIDATIONS,
)
from sentient_ledger.models.enums import (
    AssetStatus,
    DepreciationConvention,
    DepreciationMethod,
)


class TestTBColumnMap:
    def test_required_columns_are_subset_of_column_map(self):
        """Every required column must have a mapping."""
        assert TB_REQUIRED_COLUMNS <= set(TB_COLUMN_MAP.keys())

    def test_column_map_has_expected_count(self):
        assert len(TB_COLUMN_MAP) == 13


class TestFAColumnMap:
    def test_required_columns_are_subset_of_column_map(self):
        assert FA_REQUIRED_COLUMNS <= set(FA_COLUMN_MAP.keys())

    def test_column_map_has_expected_count(self):
        assert len(FA_COLUMN_MAP) == 13


class TestEnumMaps:
    def test_depreciation_method_map_covers_all_implemented(self):
        """Every engine-supported method has a D365 mapping."""
        canonical_values = {m.value for m in DepreciationMethod}
        mapped_values = set(DEPRECIATION_METHOD_MAP.values())
        assert mapped_values <= canonical_values

    def test_depreciation_convention_map_covers_all(self):
        canonical_values = {c.value for c in DepreciationConvention}
        mapped_values = set(DEPRECIATION_CONVENTION_MAP.values())
        assert mapped_values == canonical_values

    def test_asset_status_map_targets_valid_enum(self):
        canonical_values = {s.value for s in AssetStatus}
        mapped_values = set(ASSET_STATUS_MAP.values())
        assert mapped_values <= canonical_values


class TestValidationRules:
    def test_tb_validations_have_valid_severity(self):
        for _rule, severity in TB_VALIDATIONS:
            assert severity in ("ERROR", "WARNING")

    def test_fa_validations_have_valid_severity(self):
        for _rule, severity in FA_VALIDATIONS:
            assert severity in ("ERROR", "WARNING")


class TestDSColumnMap:
    def test_required_columns_are_subset_of_column_map(self):
        assert DS_REQUIRED_COLUMNS <= set(DS_COLUMN_MAP.keys())

    def test_ds_validations_have_valid_severity(self):
        for _rule, severity in DS_VALIDATIONS:
            assert severity in ("ERROR", "WARNING")


class TestSupportedCurrencies:
    def test_usd_in_supported(self):
        assert "USD" in SUPPORTED_CURRENCIES

    def test_at_least_five_currencies(self):
        assert len(SUPPORTED_CURRENCIES) >= 5
