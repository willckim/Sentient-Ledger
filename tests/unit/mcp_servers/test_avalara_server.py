"""Unit tests for avalara_server — combined filing check (no network calls)."""

from __future__ import annotations

from sentient_ledger.config import AVALARA_COMBINED_FILING_STATES


class TestCheckCombinedFilingStates:
    def test_known_combined_states(self):
        from sentient_ledger.mcp_servers.avalara_server import check_combined_filing_states

        result = check_combined_filing_states(["HI", "WA", "IL"])
        assert "HI" in result["combined"]
        assert "WA" in result["combined"]
        assert "IL" in result["individual"]

    def test_all_individual(self):
        from sentient_ledger.mcp_servers.avalara_server import check_combined_filing_states

        result = check_combined_filing_states(["CA", "TX", "NY"])
        assert result["combined"] == []
        assert set(result["individual"]) == {"CA", "TX", "NY"}

    def test_all_combined(self):
        from sentient_ledger.mcp_servers.avalara_server import check_combined_filing_states

        result = check_combined_filing_states(list(AVALARA_COMBINED_FILING_STATES))
        assert set(result["combined"]) == AVALARA_COMBINED_FILING_STATES
        assert result["individual"] == []

    def test_empty_input(self):
        from sentient_ledger.mcp_servers.avalara_server import check_combined_filing_states

        result = check_combined_filing_states([])
        assert result["combined"] == []
        assert result["individual"] == []

    def test_lowercase_normalized(self):
        from sentient_ledger.mcp_servers.avalara_server import check_combined_filing_states

        result = check_combined_filing_states(["hi", "wa"])
        assert "HI" in result["combined"]
        assert "WA" in result["combined"]

    def test_combined_filing_states_list_returned(self):
        from sentient_ledger.mcp_servers.avalara_server import check_combined_filing_states

        result = check_combined_filing_states(["CA"])
        assert set(result["combined_filing_states"]) == AVALARA_COMBINED_FILING_STATES
