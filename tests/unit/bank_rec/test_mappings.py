"""Unit tests for bank_rec/mappings.py."""

import pytest

from sentient_ledger.bank_rec.mappings import (
    BMO_COLUMN_MAP,
    BMO_DECIMAL_FIELDS,
    BMO_REQUIRED_COLUMNS,
    BMO_VALIDATIONS,
    CC_MERCHANT_REC_CATEGORIES,
    SERVICE_CHARGE_FEE_PATTERN,
    SERVICE_CHARGE_REBATE_PATTERN,
    VENDOR_PATTERNS,
)
from sentient_ledger.models.enums import VendorCategory


class TestBmoColumnMap:
    def test_has_eight_columns(self):
        assert len(BMO_COLUMN_MAP) == 8

    def test_posted_maps_to_posted_date(self):
        assert BMO_COLUMN_MAP["Posted"] == "posted_date"

    def test_debit_and_credit_present(self):
        assert "Debit" in BMO_COLUMN_MAP
        assert "Credit" in BMO_COLUMN_MAP

    def test_bank_rec_number_present(self):
        assert "Bank Rec #" in BMO_COLUMN_MAP

    def test_cc_merchant_rec_date_present(self):
        assert "CC Merchant Rec Date" in BMO_COLUMN_MAP


class TestRequiredAndDecimalSets:
    def test_required_columns_subset_of_map(self):
        assert BMO_REQUIRED_COLUMNS.issubset(set(BMO_COLUMN_MAP.keys()))

    def test_decimal_fields_subset_of_map(self):
        assert BMO_DECIMAL_FIELDS.issubset(set(BMO_COLUMN_MAP.keys()))

    def test_balance_is_required(self):
        assert "Balance" in BMO_REQUIRED_COLUMNS


class TestVendorPatterns:
    def test_elavon_cms_before_elavon(self):
        """ELAVON CMS must appear before generic ELAVON."""
        keys = [p[0] for p in VENDOR_PATTERNS]
        assert keys.index("ELAVON CMS") < keys.index("ELAVON")

    def test_rebate_before_fee(self):
        """FULL PLAN FEE REBATE must appear before PLAN FEE."""
        keys = [p[0] for p in VENDOR_PATTERNS]
        assert keys.index("FULL PLAN FEE REBATE") < keys.index("PLAN FEE")

    def test_all_categories_are_vendor_category(self):
        for _, cat in VENDOR_PATTERNS:
            assert isinstance(cat, VendorCategory)


class TestValidationRules:
    def test_five_rules(self):
        assert len(BMO_VALIDATIONS) == 5

    def test_all_have_severity(self):
        for rule in BMO_VALIDATIONS:
            assert rule["severity"] in {"ERROR", "WARNING"}

    def test_cc_merchant_rec_categories(self):
        assert "CC_MERCHANT_SETTLEMENT" in CC_MERCHANT_REC_CATEGORIES
        assert "AMEX_SETTLEMENT" in CC_MERCHANT_REC_CATEGORIES

    def test_service_charge_patterns(self):
        assert "PLAN FEE" in SERVICE_CHARGE_FEE_PATTERN
        assert "REBATE" in SERVICE_CHARGE_REBATE_PATTERN
