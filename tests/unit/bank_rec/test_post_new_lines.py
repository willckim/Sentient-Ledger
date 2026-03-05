"""Unit tests for bank_rec/post_new_lines.py."""

import uuid
from datetime import date
from decimal import Decimal

import pandas as pd
import pytest

from sentient_ledger.bank_rec.post_new_lines import (
    _auto_populate_cc_merchant_date,
    _identify_new_rows,
    _map_bmo_row_to_transaction,
    _recalculate_running_balance,
    post_new_lines,
)
from sentient_ledger.models.enums import ReconciliationStatus, TransactionType, VendorCategory

CLEAN_CSV = """\
Posted,Value Date,Description,Debit,Credit,Balance,Bank Rec #,CC Merchant Rec Date
3/4/2026,3/4/2026,AMEX SETTLEMENT,,1800.00,109975.00,,
3/4/2026,3/4/2026,ELAVON MERCHANT SETTLEMENT,,4500.00,114475.00,,
"""

EXISTING_CSV = """\
Posted,Value Date,Description,Debit,Credit,Balance,Bank Rec #,CC Merchant Rec Date
3/4/2026,3/4/2026,AMEX SETTLEMENT,,1800.00,109975.00,,
"""


class TestIdentifyNewRows:
    def test_all_new_when_existing_empty(self):
        bmo_df = pd.DataFrame({
            "Posted": ["3/1/2026"],
            "Description": ["ELAVON"],
            "Debit": [None],
            "Credit": ["5000.00"],
            "Balance": ["105000.00"],
        })
        existing_df = pd.DataFrame(columns=["Posted", "Description", "Debit", "Credit"])
        result = _identify_new_rows(bmo_df, existing_df)
        assert len(result) == 1

    def test_existing_rows_excluded(self):
        bmo_df = pd.DataFrame({
            "Posted": ["3/1/2026", "3/2/2026"],
            "Description": ["ELAVON", "AMEX"],
            "Debit": [None, None],
            "Credit": ["5000.00", "3200.00"],
            "Balance": ["105000.00", "108200.00"],
        })
        existing_df = pd.DataFrame({
            "Posted": ["3/1/2026"],
            "Description": ["ELAVON"],
            "Debit": [None],
            "Credit": ["5000.00"],
        })
        result = _identify_new_rows(bmo_df, existing_df)
        assert len(result) == 1
        assert result.iloc[0]["Description"] == "AMEX"


class TestAutoPopulateCcMerchantDate:
    def test_amex_without_date_gets_posted_date(self):
        from sentient_ledger.models.bank_reconciliation import BankTransaction, BankTransactionIntegrity

        txn = BankTransaction(
            record_id=str(uuid.uuid4()),
            ingestion_id="x",
            ingested_at="2026-03-01T00:00:00+00:00",
            posted_date=date(2026, 3, 4),
            description="AMEX SETTLEMENT",
            transaction_type=TransactionType.CREDIT,
            amount=Decimal("1800"),
            balance=Decimal("109975"),
            vendor_category=VendorCategory.AMEX_SETTLEMENT,
            cc_merchant_rec_date=None,
            integrity=BankTransactionIntegrity(source_row_hash="h", balance_verified=False),
        )
        result = _auto_populate_cc_merchant_date([txn])
        assert result[0].cc_merchant_rec_date == date(2026, 3, 4)

    def test_non_cc_vendor_unchanged(self):
        from sentient_ledger.models.bank_reconciliation import BankTransaction, BankTransactionIntegrity

        txn = BankTransaction(
            record_id=str(uuid.uuid4()),
            ingestion_id="x",
            ingested_at="2026-03-01T00:00:00+00:00",
            posted_date=date(2026, 3, 4),
            description="PAYROLL",
            transaction_type=TransactionType.CREDIT,
            amount=Decimal("500"),
            balance=Decimal("1500"),
            vendor_category=VendorCategory.PAYMENT_PROCESSING,
            cc_merchant_rec_date=None,
            integrity=BankTransactionIntegrity(source_row_hash="h", balance_verified=False),
        )
        result = _auto_populate_cc_merchant_date([txn])
        assert result[0].cc_merchant_rec_date is None


class TestRecalculateRunningBalance:
    def test_credit_adds_to_balance(self):
        from sentient_ledger.models.bank_reconciliation import BankTransaction, BankTransactionIntegrity

        txn = BankTransaction(
            record_id=str(uuid.uuid4()),
            ingestion_id="x",
            ingested_at="2026-03-01T00:00:00+00:00",
            posted_date=date(2026, 3, 1),
            description="DEPOSIT",
            transaction_type=TransactionType.CREDIT,
            amount=Decimal("500"),
            balance=Decimal("0"),
            vendor_category=VendorCategory.UNKNOWN,
            integrity=BankTransactionIntegrity(source_row_hash="h", balance_verified=False),
        )
        result = _recalculate_running_balance([txn], Decimal("1000"))
        assert result[0].balance == Decimal("1500")
        assert result[0].integrity.balance_verified

    def test_debit_subtracts_from_balance(self):
        from sentient_ledger.models.bank_reconciliation import BankTransaction, BankTransactionIntegrity

        txn = BankTransaction(
            record_id=str(uuid.uuid4()),
            ingestion_id="x",
            ingested_at="2026-03-01T00:00:00+00:00",
            posted_date=date(2026, 3, 1),
            description="FEE",
            transaction_type=TransactionType.DEBIT,
            amount=Decimal("50"),
            balance=Decimal("0"),
            vendor_category=VendorCategory.BANK_FEE,
            integrity=BankTransactionIntegrity(source_row_hash="h", balance_verified=False),
        )
        result = _recalculate_running_balance([txn], Decimal("1000"))
        assert result[0].balance == Decimal("950")


class TestPostNewLinesE2E:
    def test_no_input_returns_empty_batch(self):
        batch, validation, audits = post_new_lines()
        assert batch.total_rows == 0
        assert batch.status == ReconciliationStatus.PENDING

    def test_no_new_rows_returns_staged(self):
        existing_df = pd.DataFrame({
            "Posted": ["3/4/2026", "3/4/2026"],
            "Description": ["AMEX SETTLEMENT", "ELAVON MERCHANT SETTLEMENT"],
            "Debit": [None, None],
            "Credit": ["1800.00", "4500.00"],
            "Balance": ["109975.00", "114475.00"],
        })
        batch, validation, audits = post_new_lines(
            bmo_csv_content=CLEAN_CSV,
            existing_df=existing_df,
            opening_balance=Decimal("108175"),
        )
        assert batch.new_rows == 0
        assert batch.status == ReconciliationStatus.STAGED

    def test_new_rows_are_identified(self):
        existing_df = pd.DataFrame({
            "Posted": ["3/4/2026"],
            "Description": ["AMEX SETTLEMENT"],
            "Debit": [None],
            "Credit": ["1800.00"],
            "Balance": ["109975.00"],
        })
        batch, validation, audits = post_new_lines(
            bmo_csv_content=CLEAN_CSV,
            existing_df=existing_df,
            opening_balance=Decimal("109975"),
        )
        assert batch.new_rows == 1
        assert batch.skipped_rows == 1

    def test_audit_records_generated(self):
        batch, validation, audits = post_new_lines(
            bmo_csv_content=CLEAN_CSV,
            opening_balance=Decimal("108175"),
        )
        assert len(audits) == 2
        assert audits[0]["event_type"] == "CREATED"
