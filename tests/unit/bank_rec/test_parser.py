"""Unit tests for bank_rec/parser.py."""

import pytest

from sentient_ledger.bank_rec.parser import parse_bmo_csv_file, parse_bmo_csv_string

CLEAN_CSV = """\
Posted,Value Date,Description,Debit,Credit,Balance,Bank Rec #,CC Merchant Rec Date
3/1/2026,3/1/2026,ELAVON MERCHANT SETTLEMENT,,5000.00,105000.00,,
3/2/2026,3/2/2026,AMEX SETTLEMENT,,3200.00,108200.00,,
"""

MISSING_BALANCE_CSV = """\
Posted,Value Date,Description,Debit,Credit
3/1/2026,3/1/2026,ELAVON,,5000.00
"""


class TestParseBmoCsvString:
    def test_clean_csv_returns_dataframe(self):
        result = parse_bmo_csv_string(CLEAN_CSV)
        assert result.df is not None
        assert result.total_rows == 2
        assert not result.parse_errors

    def test_headers_extracted(self):
        result = parse_bmo_csv_string(CLEAN_CSV)
        assert "Posted" in result.headers
        assert "Balance" in result.headers

    def test_decimal_coercion(self):
        result = parse_bmo_csv_string(CLEAN_CSV)
        from decimal import Decimal
        assert result.df["Balance"].iloc[0] == Decimal("105000.00")

    def test_bom_stripped(self):
        bom_csv = "\ufeff" + CLEAN_CSV
        result = parse_bmo_csv_string(bom_csv)
        assert result.df is not None
        assert not result.parse_errors

    def test_whitespace_trimmed(self):
        spaced = "Posted , Value Date , Description , Debit , Credit , Balance , Bank Rec # , CC Merchant Rec Date\n3/1/2026 , 3/1/2026 , ELAVON , , 100.00 , 1000.00 , ,\n"
        result = parse_bmo_csv_string(spaced)
        assert result.df is not None

    def test_empty_rows_dropped(self):
        csv_with_blanks = CLEAN_CSV + "\n\n"
        result = parse_bmo_csv_string(csv_with_blanks)
        assert result.total_rows == 2

    def test_empty_content_returns_error(self):
        result = parse_bmo_csv_string("")
        assert result.df is None
        assert result.parse_errors

    def test_missing_required_column_returns_error(self):
        result = parse_bmo_csv_string(MISSING_BALANCE_CSV)
        assert result.df is None
        assert any("Balance" in e for e in result.parse_errors)


class TestParseBmoCsvFile:
    def test_file_not_found_returns_error(self, tmp_path):
        result = parse_bmo_csv_file(tmp_path / "nonexistent.csv")
        assert result.df is None
        assert result.parse_errors

    def test_reads_real_fixture(self):
        import os
        fixture = os.path.join(
            os.path.dirname(__file__), "..", "..", "fixtures", "bmo", "bmo_download_clean.csv"
        )
        result = parse_bmo_csv_file(fixture)
        assert result.df is not None
        assert result.total_rows == 5
