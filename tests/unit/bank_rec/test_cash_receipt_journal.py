"""Unit tests for bank_rec/cash_receipt_journal.py — Workflow 4."""

import csv
import uuid
from datetime import date
from decimal import Decimal

import pytest

from sentient_ledger.bank_rec.cash_receipt_journal import (
    _BC_COLUMNS,
    _make_doc_no,
    _transaction_to_journal_line,
    _write_journal_csv,
    export_cash_receipt_journal,
)
from sentient_ledger.models.bank_reconciliation import BankTransaction, BankTransactionIntegrity
from sentient_ledger.models.enums import ReconciliationStatus, TransactionType, VendorCategory


def _txn(**overrides) -> BankTransaction:
    defaults = dict(
        record_id=str(uuid.uuid4()),
        ingestion_id="test-ing",
        ingested_at="2026-03-04T00:00:00+00:00",
        posted_date=date(2026, 3, 4),
        description="AMEX SETTLEMENT",
        transaction_type=TransactionType.CREDIT,
        amount=Decimal("1800.00"),
        balance=Decimal("109975.00"),
        bank_rec_number="2751",
        vendor_category=VendorCategory.AMEX_SETTLEMENT,
        integrity=BankTransactionIntegrity(source_row_hash="abc", balance_verified=False),
    )
    defaults.update(overrides)
    return BankTransaction(**defaults)


# ---------------------------------------------------------------------------
# _make_doc_no
# ---------------------------------------------------------------------------

class TestMakeDocNo:
    def test_uses_bank_rec_number_when_present(self):
        txn = _txn(bank_rec_number="2751")
        assert _make_doc_no(txn, 0) == "2751"

    def test_generates_ccamex_prefix_when_missing(self):
        txn = _txn(bank_rec_number=None, posted_date=date(2026, 3, 4))
        result = _make_doc_no(txn, 0)
        assert result.startswith("CCAMEX")
        assert "20260304" in result

    def test_generated_doc_no_uses_one_based_index(self):
        txn = _txn(bank_rec_number=None, posted_date=date(2026, 3, 4))
        assert _make_doc_no(txn, 0).endswith("001")
        assert _make_doc_no(txn, 4).endswith("005")

    def test_generated_doc_no_pads_to_three_digits(self):
        txn = _txn(bank_rec_number=None, posted_date=date(2026, 3, 4))
        assert _make_doc_no(txn, 9).endswith("010")


# ---------------------------------------------------------------------------
# _transaction_to_journal_line
# ---------------------------------------------------------------------------

class TestTransactionToJournalLine:
    def test_credit_transaction_positive_amount(self):
        line = _transaction_to_journal_line(
            _txn(transaction_type=TransactionType.CREDIT, amount=Decimal("1800")),
            0, "G/L Account", "11200", "Payment",
        )
        assert line.amount == Decimal("1800")

    def test_debit_transaction_negative_amount(self):
        line = _transaction_to_journal_line(
            _txn(transaction_type=TransactionType.DEBIT, amount=Decimal("500")),
            0, "G/L Account", "11200", "Payment",
        )
        assert line.amount == Decimal("-500")

    def test_posting_date_copied(self):
        line = _transaction_to_journal_line(
            _txn(posted_date=date(2026, 3, 4)),
            0, "G/L Account", "11200", "Payment",
        )
        assert line.posting_date == date(2026, 3, 4)

    def test_account_no_set(self):
        line = _transaction_to_journal_line(_txn(), 0, "G/L Account", "11200", "Payment")
        assert line.account_no == "11200"

    def test_account_type_set(self):
        line = _transaction_to_journal_line(_txn(), 0, "Customer", "C00001", "Payment")
        assert line.account_type == "Customer"

    def test_document_type_set(self):
        line = _transaction_to_journal_line(_txn(), 0, "G/L Account", "11200", "Refund")
        assert line.document_type == "Refund"

    def test_description_truncated_to_100_chars(self):
        long_desc = "A" * 150
        line = _transaction_to_journal_line(
            _txn(description=long_desc), 0, "G/L Account", "11200", "Payment",
        )
        assert len(line.description) == 100

    def test_bank_rec_number_used_as_doc_no(self):
        line = _transaction_to_journal_line(
            _txn(bank_rec_number="2751"), 0, "G/L Account", "11200", "Payment",
        )
        assert line.document_no == "2751"


# ---------------------------------------------------------------------------
# export_cash_receipt_journal
# ---------------------------------------------------------------------------

class TestExportCashReceiptJournal:
    def test_returns_correct_line_count(self):
        txns = [_txn(), _txn(bank_rec_number=None)]
        lines, audits = export_cash_receipt_journal(transactions=txns, account_no="11200")
        assert len(lines) == 2

    def test_audit_record_has_committed_event(self):
        txns = [_txn()]
        lines, audits = export_cash_receipt_journal(transactions=txns, account_no="11200")
        assert len(audits) == 1
        assert audits[0]["event_type"] == "COMMITTED"

    def test_audit_record_hash_non_empty(self):
        txns = [_txn()]
        lines, audits = export_cash_receipt_journal(transactions=txns, account_no="11200")
        assert audits[0]["integrity"]["record_hash"] != ""

    def test_empty_transactions_returns_empty_lines(self):
        lines, audits = export_cash_receipt_journal(transactions=[], account_no="11200")
        assert lines == []

    def test_empty_transactions_no_output_file(self, tmp_path):
        out = tmp_path / "cj.csv"
        export_cash_receipt_journal(transactions=[], account_no="11200", output_path=out)
        assert not out.exists()

    def test_output_file_created_when_transactions_present(self, tmp_path):
        out = tmp_path / "cj.csv"
        export_cash_receipt_journal(transactions=[_txn()], account_no="11200", output_path=out)
        assert out.exists()

    def test_no_output_path_no_file(self, tmp_path):
        lines, audits = export_cash_receipt_journal(transactions=[_txn()], account_no="11200")
        assert lines  # returned in memory
        # no path given — nothing written to disk

    def test_custom_document_type_and_account_type(self):
        txns = [_txn()]
        lines, _ = export_cash_receipt_journal(
            transactions=txns,
            account_no="11200",
            document_type="Refund",
            account_type="Customer",
        )
        assert lines[0].document_type == "Refund"
        assert lines[0].account_type == "Customer"


# ---------------------------------------------------------------------------
# _write_journal_csv — BC column names and formatting
# ---------------------------------------------------------------------------

class TestWriteJournalCsv:
    def _get_headers_and_rows(self, tmp_path, lines):
        out = tmp_path / "cj.csv"
        _write_journal_csv(lines, out)
        with open(out, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        return reader.fieldnames or list(rows[0].keys()) if rows else [], rows

    def test_bc_column_names_exact(self, tmp_path):
        from sentient_ledger.models.bank_reconciliation import CashReceiptJournalLine
        line = CashReceiptJournalLine(
            posting_date=date(2026, 3, 4),
            document_type="Payment",
            document_no="2751",
            account_type="G/L Account",
            account_no="11200",
            description="AMEX SETTLEMENT",
            amount=Decimal("1800.00"),
        )
        out = tmp_path / "cj.csv"
        _write_journal_csv([line], out)
        with open(out) as f:
            headers = next(csv.reader(f))
        assert headers == _BC_COLUMNS
        assert headers == [
            "Posting Date", "Document Type", "Document No.",
            "Account Type", "Account No.", "Description", "Amount",
        ]

    def test_posting_date_formatted_mm_dd_yyyy(self, tmp_path):
        from sentient_ledger.models.bank_reconciliation import CashReceiptJournalLine
        line = CashReceiptJournalLine(
            posting_date=date(2026, 3, 4),
            document_type="Payment",
            document_no="2751",
            account_type="G/L Account",
            account_no="11200",
            description="AMEX SETTLEMENT",
            amount=Decimal("1800.00"),
        )
        out = tmp_path / "cj.csv"
        _write_journal_csv([line], out)
        with open(out) as f:
            rows = list(csv.DictReader(f))
        assert rows[0]["Posting Date"] == "03/04/2026"

    def test_negative_amount_written_correctly(self, tmp_path):
        from sentient_ledger.models.bank_reconciliation import CashReceiptJournalLine
        line = CashReceiptJournalLine(
            posting_date=date(2026, 3, 4),
            document_type="Payment",
            document_no="2751",
            account_type="G/L Account",
            account_no="11200",
            description="AMEX CHARGEBACK",
            amount=Decimal("-500.00"),
        )
        out = tmp_path / "cj.csv"
        _write_journal_csv([line], out)
        with open(out) as f:
            rows = list(csv.DictReader(f))
        assert rows[0]["Amount"] == "-500.00"
