"""Unit tests for bank_rec/reconcile_amex.py."""

import uuid
from datetime import date
from decimal import Decimal

import pytest

from sentient_ledger.bank_rec.reconcile_amex import (
    _compute_net_balance,
    _filter_amex_rows,
    _filter_up_to_date,
    _previous_business_day,
    reconcile_amex,
)
from sentient_ledger.models.bank_reconciliation import BankTransaction, BankTransactionIntegrity
from sentient_ledger.models.enums import (
    ReconciliationStatus,
    TransactionType,
    VendorCategory,
)

AMEX_CSV = """\
Posted,Value Date,Description,Debit,Credit,Balance,Bank Rec #,CC Merchant Rec Date
3/4/2026,3/4/2026,AMEX SETTLEMENT,,1800.00,109975.00,,3/4/2026
3/4/2026,3/4/2026,ELAVON MERCHANT SETTLEMENT,,4500.00,114475.00,,3/4/2026
3/5/2026,3/5/2026,AMEX SETTLEMENT,1800.00,,112675.00,,3/5/2026
"""

NO_AMEX_CSV = """\
Posted,Value Date,Description,Debit,Credit,Balance,Bank Rec #,CC Merchant Rec Date
3/4/2026,3/4/2026,ELAVON MERCHANT SETTLEMENT,,5000.00,115000.00,,3/4/2026
"""


def _make_txn(vendor=VendorCategory.AMEX_SETTLEMENT, txn_type=TransactionType.CREDIT,
              amount=Decimal("1000"), posted=date(2026, 3, 4)) -> BankTransaction:
    return BankTransaction(
        record_id=str(uuid.uuid4()),
        ingestion_id="x",
        ingested_at="2026-03-04T00:00:00+00:00",
        posted_date=posted,
        description="AMEX SETTLEMENT",
        transaction_type=txn_type,
        amount=amount,
        balance=Decimal("10000"),
        vendor_category=vendor,
        integrity=BankTransactionIntegrity(source_row_hash="h", balance_verified=False),
    )


class TestPreviousBusinessDay:
    def test_tuesday_returns_monday(self):
        result = _previous_business_day(date(2026, 3, 3))  # Tuesday
        assert result == date(2026, 3, 2)  # Monday

    def test_monday_returns_friday(self):
        result = _previous_business_day(date(2026, 3, 2))  # Monday
        assert result == date(2026, 2, 27)  # Friday

    def test_saturday_returns_friday(self):
        result = _previous_business_day(date(2026, 3, 7))  # Saturday
        assert result == date(2026, 3, 6)  # Friday


class TestFilterAmexRows:
    def test_only_amex_kept(self):
        txns = [
            _make_txn(vendor=VendorCategory.AMEX_SETTLEMENT),
            _make_txn(vendor=VendorCategory.CC_MERCHANT_SETTLEMENT),
        ]
        result = _filter_amex_rows(txns)
        assert len(result) == 1
        assert result[0].vendor_category == VendorCategory.AMEX_SETTLEMENT

    def test_empty_input(self):
        assert _filter_amex_rows([]) == []


class TestComputeNetBalance:
    def test_net_zero(self):
        txns = [
            _make_txn(txn_type=TransactionType.CREDIT, amount=Decimal("1000")),
            _make_txn(txn_type=TransactionType.DEBIT, amount=Decimal("1000")),
        ]
        assert _compute_net_balance(txns) == Decimal("0")

    def test_net_positive(self):
        txns = [_make_txn(txn_type=TransactionType.CREDIT, amount=Decimal("1800"))]
        assert _compute_net_balance(txns) == Decimal("1800")

    def test_empty_is_zero(self):
        assert _compute_net_balance([]) == Decimal("0")


class TestReconcileAmexE2E:
    def test_no_input_returns_pending(self):
        batch, audits = reconcile_amex()
        assert batch.status == ReconciliationStatus.PENDING
        assert batch.total_rows == 0

    def test_filters_to_amex_only(self):
        batch, audits = reconcile_amex(
            bmo_csv_content=AMEX_CSV,
            cutoff_date=date(2026, 3, 5),
        )
        for txn in batch.transactions:
            assert txn.vendor_category == VendorCategory.AMEX_SETTLEMENT

    def test_net_zero_gives_reconciled_status(self):
        # credit 1800 then debit 1800 → net zero
        batch, audits = reconcile_amex(
            bmo_csv_content=AMEX_CSV,
            cutoff_date=date(2026, 3, 5),
        )
        assert batch.status == ReconciliationStatus.RECONCILED
        assert batch.balance_verified

    def test_no_amex_rows_produces_empty_batch(self):
        batch, audits = reconcile_amex(
            bmo_csv_content=NO_AMEX_CSV,
            cutoff_date=date(2026, 3, 5),
        )
        assert batch.new_rows == 0

    def test_cutoff_filter_applied(self):
        # Only cutoff up to 3/4 — the 3/5 debit row excluded, net = 1800 (not zero)
        batch, audits = reconcile_amex(
            bmo_csv_content=AMEX_CSV,
            cutoff_date=date(2026, 3, 4),
        )
        assert len(batch.transactions) == 1
        assert batch.status == ReconciliationStatus.STAGED  # not zero

    def test_output_file_written(self, tmp_path):
        out = tmp_path / "amex_out.csv"
        batch, audits = reconcile_amex(
            bmo_csv_content=AMEX_CSV,
            cutoff_date=date(2026, 3, 5),
            output_path=out,
        )
        assert out.exists()

    def test_audit_record_generated(self):
        batch, audits = reconcile_amex(
            bmo_csv_content=AMEX_CSV,
            cutoff_date=date(2026, 3, 5),
        )
        assert len(audits) == 1
        assert audits[0]["event_type"] == "CREATED"
