"""Tests for ingest CSV parser."""

from sentient_ledger.ingest.parser import parse_csv_file, parse_csv_string


class TestParseCSVString:
    def test_basic_parsing(self):
        content = "MainAccount,AccountName,Amount\n1000,Cash,5000\n2000,AP,3000\n"
        result = parse_csv_string(content)
        assert result.total_rows == 2
        assert len(result.rows) == 2
        assert result.rows[0]["MainAccount"] == "1000"
        assert result.rows[1]["AccountName"] == "AP"

    def test_bom_stripping(self):
        content = "\ufeffMainAccount,AccountName\n1000,Cash\n"
        result = parse_csv_string(content)
        assert result.total_rows == 1
        assert "MainAccount" in result.rows[0]

    def test_whitespace_trimming(self):
        content = "MainAccount , AccountName \n 1000 , Cash \n"
        result = parse_csv_string(content)
        assert result.rows[0]["MainAccount"] == "1000"
        assert result.rows[0]["AccountName"] == "Cash"

    def test_empty_rows_skipped(self):
        content = "MainAccount,AccountName\n1000,Cash\n,,\n2000,AP\n"
        result = parse_csv_string(content)
        assert result.total_rows == 2

    def test_headers_captured(self):
        content = "Col1,Col2,Col3\na,b,c\n"
        result = parse_csv_string(content)
        assert result.headers == ["Col1", "Col2", "Col3"]

    def test_empty_content_returns_zero_rows(self):
        result = parse_csv_string("")
        assert result.total_rows == 0
        assert result.rows == []

    def test_header_only_returns_zero_rows(self):
        content = "MainAccount,AccountName\n"
        result = parse_csv_string(content)
        assert result.total_rows == 0

    def test_missing_values_become_empty_string(self):
        content = "A,B,C\n1,,3\n"
        result = parse_csv_string(content)
        assert result.rows[0]["B"] == ""


class TestParseCSVFile:
    def test_file_not_found_returns_error(self, tmp_path):
        result = parse_csv_file(str(tmp_path / "nonexistent.csv"))
        assert len(result.parse_errors) > 0
        assert "not found" in result.parse_errors[0].lower()

    def test_reads_real_file(self, tmp_path):
        p = tmp_path / "test.csv"
        p.write_text("A,B\n1,2\n3,4\n", encoding="utf-8")
        result = parse_csv_file(str(p))
        assert result.total_rows == 2
        assert result.rows[0]["A"] == "1"
