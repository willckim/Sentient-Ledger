"""Unit tests for MCP-related config constants."""

from __future__ import annotations

from sentient_ledger.config import (
    AVALARA_COMBINED_FILING_STATES,
    BC_COMPANIES,
    CONCUR_PAY_GROUP,
    MCP_MAX_RETRIES,
    MCP_SERVER_TIMEOUT_SEC,
    TANGO_APPROVED_BRANDS,
)


class TestMCPConfig:
    def test_timeout_is_positive(self):
        assert MCP_SERVER_TIMEOUT_SEC > 0

    def test_max_retries_at_least_one(self):
        assert MCP_MAX_RETRIES >= 1

    def test_bc_companies_has_ortho_and_utzy(self):
        assert "ortho" in BC_COMPANIES
        assert "utzy" in BC_COMPANIES

    def test_concur_pay_group_not_empty(self):
        assert CONCUR_PAY_GROUP != ""

    def test_avalara_combined_filing_states_correct(self):
        expected = {"HI", "IA", "MO", "NM", "OH", "SC", "TN", "UT", "WA"}
        assert AVALARA_COMBINED_FILING_STATES == expected

    def test_tango_approved_brands_not_empty(self):
        assert len(TANGO_APPROVED_BRANDS) > 0

    def test_amazon_in_approved_brands(self):
        assert "Amazon" in TANGO_APPROVED_BRANDS

    def test_combined_filing_states_is_frozenset(self):
        assert isinstance(AVALARA_COMBINED_FILING_STATES, frozenset)

    def test_approved_brands_is_frozenset(self):
        assert isinstance(TANGO_APPROVED_BRANDS, frozenset)
