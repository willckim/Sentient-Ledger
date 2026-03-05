"""Integration tests for the BMO bank reconciliation module."""

import os
from datetime import date
from decimal import Decimal
from pathlib import Path

import pandas as pd
import pytest

FIXTURES = os.path.join(os.path.dirname(__file__), "..", "fixtures", "bmo")


def _fixture(name: str) -> str:
    return os.path.join(FIXTURES, name)


def _read_fixture(name: str) -> str:
    return Path(_fixture(name)).read_text(encoding="utf-8")


class TestPostNewLinesE2E:
    def test_clean_csv_produces_staged_batch(self):
        from sentient_ledger.bank_rec import post_new_lines

        batch, validation, audits = post_new_lines(
            bmo_csv_path=_fixture("bmo_download_clean.csv"),
            opening_balance=Decimal("100000.00"),
        )
        assert batch.new_rows == 5
        assert batch.total_rows == 5
        assert batch.status.value == "STAGED"
        assert validation.error_count == 0

    def test_audit_chain_integrity(self):
        from sentient_ledger.bank_rec import post_new_lines

        batch, validation, audits = post_new_lines(
            bmo_csv_content=_read_fixture("bmo_download_clean.csv"),
            opening_balance=Decimal("100000.00"),
        )
        assert len(audits) == 2
        # Second record's previous_record_hash must equal first record's record_hash
        first_hash = audits[0]["integrity"]["record_hash"]
        second_prev = audits[1]["integrity"]["previous_record_hash"]
        assert first_hash == second_prev
        assert first_hash != ""

    def test_cc_merchant_date_auto_populated(self):
        from sentient_ledger.bank_rec import post_new_lines

        batch, validation, audits = post_new_lines(
            bmo_csv_content=_read_fixture("bmo_download_clean.csv"),
            opening_balance=Decimal("100000.00"),
        )
        # First row is ELAVON MERCHANT SETTLEMENT → CC_MERCHANT_SETTLEMENT → should get date
        elavon_txns = [t for t in batch.transactions if "ELAVON" in t.description.upper()
                       and "CMS" not in t.description.upper()]
        for txn in elavon_txns:
            assert txn.cc_merchant_rec_date is not None, (
                f"Expected cc_merchant_rec_date on {txn.description}"
            )

    def test_xlsx_existing_filters_new_rows(self):
        from sentient_ledger.bank_rec import post_new_lines

        # bank_rec_cad.xlsx has rows 0-4 from bmo_download.csv (Bank Rec # 2750)
        # bmo_download.csv also has rows 5-6 (Bank Rec # 2751)
        batch, validation, audits = post_new_lines(
            bmo_csv_path=_fixture("bmo_download.csv"),
            existing_xlsx_path=_fixture("bank_rec_cad.xlsx"),
            opening_balance=Decimal("108175.00"),
        )
        assert batch.skipped_rows == 5
        assert batch.new_rows == 2

    def test_output_csv_written(self, tmp_path):
        from sentient_ledger.bank_rec import post_new_lines

        out = tmp_path / "output.csv"
        batch, validation, audits = post_new_lines(
            bmo_csv_content=_read_fixture("bmo_download_clean.csv"),
            opening_balance=Decimal("100000.00"),
            output_path=out,
        )
        assert out.exists()
        import csv
        with open(out) as f:
            rows = list(csv.DictReader(f))
        assert len(rows) == batch.new_rows


class TestReconcileGLE2E:
    def test_removes_reconciled_rows(self):
        from sentient_ledger.bank_rec import reconcile_gl

        batch, validation, audits = reconcile_gl(
            bmo_csv_path=_fixture("bmo_download.csv"),
        )
        # 5 rows have Bank Rec # 2750, 2 have 2751
        assert batch.reconciled_rows == 5
        assert batch.new_rows == 2

    def test_audit_record_created(self):
        from sentient_ledger.bank_rec import reconcile_gl

        batch, validation, audits = reconcile_gl(
            bmo_csv_content=_read_fixture("bmo_download.csv"),
        )
        assert len(audits) == 1
        assert audits[0]["integrity"]["record_hash"] != ""

    def test_output_csv_written(self, tmp_path):
        from sentient_ledger.bank_rec import reconcile_gl

        out = tmp_path / "gl_out.csv"
        batch, validation, audits = reconcile_gl(
            bmo_csv_content=_read_fixture("bmo_download.csv"),
            output_path=out,
        )
        if batch.new_rows > 0:
            assert out.exists()
        else:
            pytest.skip("No unreconciled rows in fixture — output not written")


class TestReconcileAmexE2E:
    def test_filters_to_amex_only(self):
        from sentient_ledger.bank_rec import reconcile_amex

        batch, audits = reconcile_amex(
            bmo_csv_path=_fixture("bmo_download.csv"),
            cutoff_date=date(2026, 3, 5),
        )
        from sentient_ledger.models.enums import VendorCategory
        for txn in batch.transactions:
            assert txn.vendor_category == VendorCategory.AMEX_SETTLEMENT

    def test_output_file_written(self, tmp_path):
        from sentient_ledger.bank_rec import reconcile_amex

        out = tmp_path / "amex_out.csv"
        batch, audits = reconcile_amex(
            bmo_csv_content=_read_fixture("bmo_download.csv"),
            cutoff_date=date(2026, 3, 5),
            output_path=out,
        )
        if batch.new_rows > 0:
            assert out.exists()
