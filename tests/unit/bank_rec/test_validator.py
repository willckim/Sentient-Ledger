"""Unit tests for bank_rec/validator.py."""

import uuid
from datetime import date
from decimal import Decimal

import pytest

from sentient_ledger.bank_rec.validator import (
    classify_vendor,
    validate_bank_transactions,
    validate_cc_merchant_rec_dates,
    validate_no_duplicates,
    validate_running_balance,
    validate_service_charge_pairs,
)
from sentient_ledger.models.bank_reconciliation import (
    BankTransaction,
    BankTransactionIntegrity,
)
from sentient_ledger.models.enums import TransactionType, VendorCategory


def _txn(**overrides) -> BankTransaction:
    defaults = dict(
        record_id=str(uuid.uuid4()),
        ingestion_id="test-ing",
        ingested_at="2026-03-01T00:00:00+00:00",
        posted_date=date(2026, 3, 1),
        description="GENERIC DEPOSIT",
        transaction_type=TransactionType.CREDIT,
        amount=Decimal("100.00"),
        balance=Decimal("1100.00"),
        vendor_category=VendorCategory.UNKNOWN,
        integrity=BankTransactionIntegrity(source_row_hash="abc", balance_verified=False),
    )
    defaults.update(overrides)
    return BankTransaction(**defaults)


class TestClassifyVendor:
    def test_elavon_cms_is_fee(self):
        assert classify_vendor("ELAVON CMS PROCESSING") == VendorCategory.CC_MERCHANT_FEE.value

    def test_elavon_ges_is_fee(self):
        assert classify_vendor("ELAVON GES SOMETHING") == VendorCategory.CC_MERCHANT_FEE.value

    def test_elavon_generic_is_settlement(self):
        assert classify_vendor("ELAVON MERCHANT SETTLEMENT") == VendorCategory.CC_MERCHANT_SETTLEMENT.value

    def test_amex_is_settlement(self):
        assert classify_vendor("AMEX SETTLEMENT") == VendorCategory.AMEX_SETTLEMENT.value

    def test_full_plan_fee_rebate_is_rebate(self):
        assert classify_vendor("FULL PLAN FEE REBATE") == VendorCategory.BANK_FEE_REBATE.value

    def test_plan_fee_is_bank_fee(self):
        assert classify_vendor("MONTHLY PLAN FEE") == VendorCategory.BANK_FEE.value

    def test_payroll_is_payment_processing(self):
        assert classify_vendor("PAYROLL DIRECT DEP") == VendorCategory.PAYMENT_PROCESSING.value

    def test_401k_is_retirement(self):
        assert classify_vendor("401K CONTRIBUTION") == VendorCategory.RETIREMENT_PLAN.value

    def test_unknown_falls_back(self):
        assert classify_vendor("MISC TRANSFER XYZABC") == VendorCategory.UNKNOWN.value

    def test_case_insensitive(self):
        assert classify_vendor("amex settlement") == VendorCategory.AMEX_SETTLEMENT.value


class TestValidateRunningBalance:
    def test_correct_chain_no_issues(self):
        txns = [
            _txn(amount=Decimal("100"), balance=Decimal("1100"), transaction_type=TransactionType.CREDIT),
            _txn(amount=Decimal("50"), balance=Decimal("1150"), transaction_type=TransactionType.CREDIT),
            _txn(amount=Decimal("30"), balance=Decimal("1120"), transaction_type=TransactionType.DEBIT),
        ]
        issues = validate_running_balance(txns)
        assert issues == []

    def test_broken_chain_flags_error(self):
        txns = [
            _txn(amount=Decimal("100"), balance=Decimal("1100"), transaction_type=TransactionType.CREDIT),
            _txn(amount=Decimal("50"), balance=Decimal("9999"), transaction_type=TransactionType.CREDIT),
        ]
        issues = validate_running_balance(txns)
        assert len(issues) == 1
        assert issues[0].rule == "RUNNING_BALANCE"
        assert issues[0].severity == "ERROR"

    def test_single_row_no_issues(self):
        txns = [_txn()]
        issues = validate_running_balance(txns)
        assert issues == []


class TestValidateNoDuplicates:
    def test_unique_rows_no_issues(self):
        txns = [
            _txn(posted_date=date(2026, 3, 1), description="A", amount=Decimal("100")),
            _txn(posted_date=date(2026, 3, 2), description="A", amount=Decimal("100")),
        ]
        issues = validate_no_duplicates(txns)
        assert issues == []

    def test_duplicate_flagged(self):
        txns = [
            _txn(posted_date=date(2026, 3, 1), description="AMEX", amount=Decimal("500")),
            _txn(posted_date=date(2026, 3, 1), description="AMEX", amount=Decimal("500")),
        ]
        issues = validate_no_duplicates(txns)
        assert len(issues) == 1
        assert issues[0].rule == "NO_DUPLICATES"


class TestValidateServiceChargePairs:
    def test_matched_pair_no_issue(self):
        txns = [
            _txn(description="PLAN FEE", amount=Decimal("50"), transaction_type=TransactionType.DEBIT,
                 vendor_category=VendorCategory.BANK_FEE),
            _txn(description="FULL PLAN FEE REBATE", amount=Decimal("50"), transaction_type=TransactionType.CREDIT,
                 vendor_category=VendorCategory.BANK_FEE_REBATE),
        ]
        issues, pairs = validate_service_charge_pairs(txns)
        assert issues == []
        assert len(pairs) == 1
        assert pairs[0].is_net_zero

    def test_unmatched_fee_warns(self):
        txns = [
            _txn(description="PLAN FEE", amount=Decimal("50"), transaction_type=TransactionType.DEBIT,
                 vendor_category=VendorCategory.BANK_FEE),
        ]
        issues, pairs = validate_service_charge_pairs(txns)
        assert len(issues) == 1
        assert issues[0].severity == "WARNING"

    def test_no_service_charges_clean(self):
        txns = [_txn(description="RANDOM PAYMENT")]
        issues, pairs = validate_service_charge_pairs(txns)
        assert issues == []
        assert pairs == []


class TestValidateCcMerchantRecDates:
    def test_elavon_with_date_no_warning(self):
        txns = [
            _txn(
                vendor_category=VendorCategory.CC_MERCHANT_SETTLEMENT,
                cc_merchant_rec_date=date(2026, 3, 1),
            )
        ]
        issues = validate_cc_merchant_rec_dates(txns)
        assert issues == []

    def test_amex_missing_date_warns(self):
        txns = [
            _txn(
                vendor_category=VendorCategory.AMEX_SETTLEMENT,
                cc_merchant_rec_date=None,
            )
        ]
        issues = validate_cc_merchant_rec_dates(txns)
        assert len(issues) == 1
        assert issues[0].severity == "WARNING"
        assert issues[0].rule == "CC_MERCHANT_REC_DATE"

    def test_unknown_vendor_no_warning(self):
        txns = [_txn(vendor_category=VendorCategory.UNKNOWN, cc_merchant_rec_date=None)]
        issues = validate_cc_merchant_rec_dates(txns)
        assert issues == []


class TestValidateBankTransactions:
    def test_clean_transactions_pass(self):
        txns = [
            _txn(amount=Decimal("100"), balance=Decimal("1100"), transaction_type=TransactionType.CREDIT,
                 vendor_category=VendorCategory.CC_MERCHANT_SETTLEMENT,
                 cc_merchant_rec_date=date(2026, 3, 1)),
        ]
        result = validate_bank_transactions(txns)
        assert result.error_count == 0
        assert result.valid_transactions == txns

    def test_error_clears_valid_transactions(self):
        # Two rows with same key → duplicate error
        txns = [
            _txn(posted_date=date(2026, 3, 1), description="X", amount=Decimal("100")),
            _txn(posted_date=date(2026, 3, 1), description="X", amount=Decimal("100")),
        ]
        result = validate_bank_transactions(txns)
        assert result.error_count > 0
        assert result.valid_transactions == []
