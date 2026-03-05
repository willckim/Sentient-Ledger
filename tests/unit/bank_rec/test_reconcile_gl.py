"""Unit tests for bank_rec/reconcile_gl.py."""

import pytest
from decimal import Decimal
from datetime import date

from sentient_ledger.bank_rec.reconcile_gl import (
    _remove_reconciled_rows,
    _verify_ending_balance,
    reconcile_gl,
)
from sentient_ledger.models.enums import ReconciliationStatus

import pandas as pd

MIXED_CSV = """\
Posted,Value Date,Description,Debit,Credit,Balance,Bank Rec #,CC Merchant Rec Date
3/1/2026,3/1/2026,ELAVON MERCHANT SETTLEMENT,,5000.00,105000.00,2750,3/1/2026
3/4/2026,3/4/2026,AMEX SETTLEMENT,,1800.00,106800.00,,3/4/2026
"""

ALL_RECONCILED_CSV = """\
Posted,Value Date,Description,Debit,Credit,Balance,Bank Rec #,CC Merchant Rec Date
3/1/2026,3/1/2026,ELAVON,,5000.00,105000.00,2750,
"""


class TestRemoveReconciledRows:
    def test_removes_rows_with_bank_rec_number(self):
        df = pd.DataFrame({
            "Posted": ["3/1/2026", "3/4/2026"],
            "Description": ["ELAVON", "AMEX"],
            "Bank Rec #": ["2750", ""],
        })
        unreconciled, count = _remove_reconciled_rows(df)
        assert count == 1
        assert len(unreconciled) == 1
        assert unreconciled.iloc[0]["Description"] == "AMEX"

    def test_empty_bank_rec_treated_as_unreconciled(self):
        df = pd.DataFrame({
            "Bank Rec #": ["", None, "2750"],
        })
        unreconciled, count = _remove_reconciled_rows(df)
        assert count == 1
        assert len(unreconciled) == 2


class TestVerifyEndingBalance:
    def test_match_returns_true(self):
        from sentient_ledger.models.bank_reconciliation import BankTransaction, BankTransactionIntegrity
        from sentient_ledger.models.enums import TransactionType, VendorCategory
        import uuid

        txn = BankTransaction(
            record_id=str(uuid.uuid4()),
            ingestion_id="x",
            ingested_at="2026-03-01T00:00:00+00:00",
            posted_date=date(2026, 3, 1),
            description="X",
            transaction_type=TransactionType.CREDIT,
            amount=Decimal("100"),
            balance=Decimal("1100"),
            vendor_category=VendorCategory.UNKNOWN,
            integrity=BankTransactionIntegrity(source_row_hash="h", balance_verified=False),
        )
        assert _verify_ending_balance([txn], Decimal("1100"))

    def test_mismatch_returns_false(self):
        from sentient_ledger.models.bank_reconciliation import BankTransaction, BankTransactionIntegrity
        from sentient_ledger.models.enums import TransactionType, VendorCategory
        import uuid

        txn = BankTransaction(
            record_id=str(uuid.uuid4()),
            ingestion_id="x",
            ingested_at="2026-03-01T00:00:00+00:00",
            posted_date=date(2026, 3, 1),
            description="X",
            transaction_type=TransactionType.CREDIT,
            amount=Decimal("100"),
            balance=Decimal("1100"),
            vendor_category=VendorCategory.UNKNOWN,
            integrity=BankTransactionIntegrity(source_row_hash="h", balance_verified=False),
        )
        assert not _verify_ending_balance([txn], Decimal("9999"))


class TestReconcileGlE2E:
    def test_no_input_returns_pending_batch(self):
        batch, validation, audits = reconcile_gl()
        assert batch.status == ReconciliationStatus.PENDING
        assert batch.total_rows == 0

    def test_removes_reconciled_rows(self):
        batch, validation, audits = reconcile_gl(bmo_csv_content=MIXED_CSV)
        assert batch.reconciled_rows == 1
        assert batch.new_rows == 1

    def test_balance_verification_pass(self):
        batch, validation, audits = reconcile_gl(
            bmo_csv_content=MIXED_CSV,
            expected_ending_balance=Decimal("106800.00"),
        )
        assert batch.balance_verified

    def test_balance_verification_fail(self):
        batch, validation, audits = reconcile_gl(
            bmo_csv_content=MIXED_CSV,
            expected_ending_balance=Decimal("999999.00"),
        )
        assert not batch.balance_verified

    def test_audit_record_created(self):
        batch, validation, audits = reconcile_gl(bmo_csv_content=MIXED_CSV)
        assert len(audits) == 1
        assert audits[0]["event_type"] == "CREATED"
