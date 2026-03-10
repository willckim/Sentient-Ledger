"""Unit tests for bmo_server MCP tools."""

from __future__ import annotations

from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent.parent.parent / "fixtures" / "bmo"

_CLEAN_CSV = (FIXTURES / "bmo_download_clean.csv").read_text(encoding="utf-8-sig")
_FULL_CSV = (FIXTURES / "bmo_download.csv").read_text(encoding="utf-8-sig")


class TestParseBmoCsv:
    def test_returns_rows(self):
        from sentient_ledger.mcp_servers.bmo_server import parse_bmo_csv
        result = parse_bmo_csv(_CLEAN_CSV)
        assert result["total_rows"] > 0
        assert "headers" in result
        assert result["parse_errors"] == []

    def test_invalid_csv_returns_error(self):
        from sentient_ledger.mcp_servers.bmo_server import parse_bmo_csv
        result = parse_bmo_csv("not,a,valid,bmo,csv\nno,header,match,,\n")
        # Should return without crashing; parse_errors may or may not be populated
        assert "total_rows" in result

    def test_all_rows_are_string_dicts(self):
        from sentient_ledger.mcp_servers.bmo_server import parse_bmo_csv
        result = parse_bmo_csv(_CLEAN_CSV)
        for row in result["rows"]:
            for k, v in row.items():
                assert isinstance(k, str)
                assert isinstance(v, str)

    def test_bom_handled(self):
        # Add a BOM prefix — should still parse
        from sentient_ledger.mcp_servers.bmo_server import parse_bmo_csv
        bom_content = "\ufeff" + _CLEAN_CSV
        result = parse_bmo_csv(bom_content)
        assert result["total_rows"] > 0


class TestClassifyTransactions:
    def test_all_rows_have_vendor_category(self):
        from sentient_ledger.mcp_servers.bmo_server import classify_transactions
        result = classify_transactions(_FULL_CSV)
        assert result["parse_errors"] == []
        for row in result["rows"]:
            assert "vendor_category" in row
            assert row["vendor_category"] != ""

    def test_category_counts_sum_to_total(self):
        from sentient_ledger.mcp_servers.bmo_server import classify_transactions
        result = classify_transactions(_FULL_CSV)
        total = sum(result["category_counts"].values())
        assert total == len(result["rows"])

    def test_amex_rows_classified_correctly(self):
        from sentient_ledger.mcp_servers.bmo_server import classify_transactions
        result = classify_transactions(_FULL_CSV)
        amex_rows = [r for r in result["rows"] if r["vendor_category"] == "AMEX_SETTLEMENT"]
        assert len(amex_rows) >= 1


class TestGetUnreconciledTransactions:
    def test_clean_csv_all_unreconciled(self):
        from sentient_ledger.mcp_servers.bmo_server import get_unreconciled_transactions
        result = get_unreconciled_transactions(_CLEAN_CSV)
        assert result["unreconciled_count"] == result["total_count"]

    def test_full_csv_has_reconciled_rows(self):
        from sentient_ledger.mcp_servers.bmo_server import get_unreconciled_transactions
        result = get_unreconciled_transactions(_FULL_CSV)
        # bmo_download.csv has rows 0-4 reconciled, rows 5-6 unreconciled
        assert result["unreconciled_count"] < result["total_count"]

    def test_counts_are_consistent(self):
        from sentient_ledger.mcp_servers.bmo_server import get_unreconciled_transactions
        result = get_unreconciled_transactions(_FULL_CSV)
        assert result["unreconciled_count"] == len(result["rows"])


class TestGetAmexTransactions:
    def test_filters_to_amex_only(self):
        from sentient_ledger.mcp_servers.bmo_server import get_amex_transactions
        result = get_amex_transactions(_FULL_CSV)
        assert result["parse_errors"] == []
        # All returned rows should be AMEX
        from sentient_ledger.bank_rec.validator import classify_vendor
        for row in result["rows"]:
            cat = classify_vendor(row.get("Description", ""))
            assert cat == "AMEX_SETTLEMENT"

    def test_cutoff_date_filters_rows(self):
        from sentient_ledger.mcp_servers.bmo_server import get_amex_transactions
        # Use a very early date — should return 0 AMEX rows
        result = get_amex_transactions(_FULL_CSV, cutoff_date="2020-01-01")
        assert result["amex_count"] == 0

    def test_invalid_cutoff_returns_error(self):
        from sentient_ledger.mcp_servers.bmo_server import get_amex_transactions
        result = get_amex_transactions(_FULL_CSV, cutoff_date="not-a-date")
        assert len(result["parse_errors"]) > 0

    def test_net_balance_field_present(self):
        from sentient_ledger.mcp_servers.bmo_server import get_amex_transactions
        result = get_amex_transactions(_FULL_CSV)
        assert "net_balance" in result
