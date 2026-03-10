"""Integration tests for MCP servers.

Tests that require live credentials are skipped automatically when the relevant
environment variables are not set.  CI runs skip all credential-gated tests.

Local development: set the env vars in .env (never commit it) to run live tests.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from sentient_ledger.models.mcp import MCPToolCall
from sentient_ledger.mcp_servers.orchestrator import (
    call_tool,
    call_tool_with_fallback,
    clear_connection_log,
    get_connection_log,
    health_check_all,
)

FIXTURES = Path(__file__).parent.parent / "fixtures" / "bmo"
_FULL_CSV = (FIXTURES / "bmo_download.csv").read_text(encoding="utf-8-sig")

# ---------------------------------------------------------------------------
# skip markers
# ---------------------------------------------------------------------------

_need_bc = pytest.mark.skipif(
    not os.environ.get("BC_TENANT_ID"),
    reason="BC credentials not set (BC_TENANT_ID missing)",
)
_need_concur = pytest.mark.skipif(
    not os.environ.get("CONCUR_CLIENT_ID"),
    reason="Concur credentials not set",
)
_need_avalara = pytest.mark.skipif(
    not os.environ.get("AVALARA_ACCOUNT_ID"),
    reason="Avalara credentials not set",
)
_need_tango = pytest.mark.skipif(
    not os.environ.get("TANGO_PLATFORM_NAME"),
    reason="Tango credentials not set",
)


@pytest.fixture(autouse=True)
def reset_log():
    clear_connection_log()
    yield
    clear_connection_log()


# ---------------------------------------------------------------------------
# BMO — always runs (no credentials)
# ---------------------------------------------------------------------------


class TestBMOIntegration:
    def test_parse_full_csv_returns_all_rows(self):
        tc = MCPToolCall(
            server_name="bmo",
            tool_name="parse_bmo_csv",
            arguments={"csv_content": _FULL_CSV},
        )
        result = call_tool(tc)
        assert result.success is True
        assert result.data["total_rows"] == 7

    def test_classify_transactions_no_unknown_in_full_csv(self):
        tc = MCPToolCall(
            server_name="bmo",
            tool_name="classify_transactions",
            arguments={"csv_content": _FULL_CSV},
        )
        result = call_tool(tc)
        assert result.success is True
        # Every row should have a non-empty category
        for row in result.data["rows"]:
            assert row["vendor_category"] != ""

    def test_get_unreconciled_returns_two_rows(self):
        tc = MCPToolCall(
            server_name="bmo",
            tool_name="get_unreconciled_transactions",
            arguments={"csv_content": _FULL_CSV},
        )
        result = call_tool(tc)
        assert result.success is True
        # Rows 5-6 in bmo_download.csv have no Bank Rec #
        assert result.data["unreconciled_count"] == 2

    def test_get_amex_transactions_count(self):
        tc = MCPToolCall(
            server_name="bmo",
            tool_name="get_amex_transactions",
            arguments={"csv_content": _FULL_CSV, "cutoff_date": "2026-03-05"},
        )
        result = call_tool(tc)
        assert result.success is True
        # bmo_download.csv has 2 AMEX rows
        assert result.data["amex_count"] == 2

    def test_connection_log_populated(self):
        tc = MCPToolCall(server_name="bmo", tool_name="parse_bmo_csv", arguments={"csv_content": _FULL_CSV})
        call_tool(tc)
        log = get_connection_log()
        assert len(log) == 1
        assert log[0].server_name == "bmo"


# ---------------------------------------------------------------------------
# File system — always runs (uses tmp_path-based drive root)
# ---------------------------------------------------------------------------


class TestFileSystemIntegration:
    @pytest.fixture()
    def drive(self, tmp_path, monkeypatch):
        monkeypatch.setenv("FS_DRIVE_ROOT", str(tmp_path))
        return tmp_path

    def test_write_then_read_roundtrip(self, drive):
        write_tc = MCPToolCall(
            server_name="filesystem",
            tool_name="write_csv",
            arguments={
                "relative_path": "bank_rec/output.csv",
                "headers": ["Date", "Amount"],
                "rows": [{"Date": "2026-03-01", "Amount": "1000.00"}],
            },
        )
        write_result = call_tool(write_tc)
        assert write_result.success is True
        assert write_result.data["written_rows"] == 1

        read_tc = MCPToolCall(
            server_name="filesystem",
            tool_name="read_csv",
            arguments={"relative_path": "bank_rec/output.csv"},
        )
        read_result = call_tool(read_tc)
        assert read_result.success is True
        assert read_result.data["total_rows"] == 1
        assert read_result.data["rows"][0]["Amount"] == "1000.00"

    def test_file_exists_after_write(self, drive):
        call_tool(
            MCPToolCall(
                server_name="filesystem",
                tool_name="write_csv",
                arguments={
                    "relative_path": "check.csv",
                    "headers": ["x"],
                    "rows": [{"x": "1"}],
                },
            )
        )
        result = call_tool(
            MCPToolCall(
                server_name="filesystem",
                tool_name="file_exists",
                arguments={"relative_path": "check.csv"},
            )
        )
        assert result.data["exists"] is True

    def test_get_latest_file_after_two_writes(self, drive):
        import time

        call_tool(
            MCPToolCall(
                server_name="filesystem",
                tool_name="write_csv",
                arguments={"relative_path": "first.csv", "headers": ["x"], "rows": [{"x": "1"}]},
            )
        )
        time.sleep(0.05)
        call_tool(
            MCPToolCall(
                server_name="filesystem",
                tool_name="write_csv",
                arguments={"relative_path": "second.csv", "headers": ["x"], "rows": [{"x": "2"}]},
            )
        )
        result = call_tool(
            MCPToolCall(
                server_name="filesystem",
                tool_name="get_latest_file",
                arguments={"relative_dir": "", "pattern": "*.csv"},
            )
        )
        assert result.data["path"].endswith("second.csv")


# ---------------------------------------------------------------------------
# Fallback — always runs
# ---------------------------------------------------------------------------


class TestFallbackBehavior:
    def test_bmo_fallback_from_bad_tool(self):
        """If a tool call fails, the fallback callable is invoked."""
        fallback_data = {"fallback": True, "rows": []}

        def file_ingest_fallback():
            return fallback_data

        tc = MCPToolCall(server_name="nonexistent", tool_name="do_thing")
        result = call_tool_with_fallback(tc, fallback_fn=file_ingest_fallback)
        assert result.success is True
        assert result.data == fallback_data

    def test_fallback_logged_with_flag(self):
        def fallback():
            return {}

        tc = MCPToolCall(server_name="nonexistent", tool_name="tool")
        call_tool_with_fallback(tc, fallback_fn=fallback)
        log = get_connection_log()
        fallback_entries = [e for e in log if e.fallback_used]
        assert len(fallback_entries) >= 1


# ---------------------------------------------------------------------------
# BC — credential-gated
# ---------------------------------------------------------------------------


@_need_bc
class TestBCIntegration:
    def test_health_check_returns_healthy(self):
        result = call_tool(MCPToolCall(server_name="bc", tool_name="health_check_bc"))
        assert result.success is True
        assert result.data["healthy"] is True

    def test_get_companies_returns_list(self):
        result = call_tool(MCPToolCall(server_name="bc", tool_name="get_companies"))
        assert result.success is True
        assert isinstance(result.data["companies"], list)


# ---------------------------------------------------------------------------
# Concur — credential-gated
# ---------------------------------------------------------------------------


@_need_concur
class TestConcurIntegration:
    def test_health_check_returns_healthy(self):
        result = call_tool(MCPToolCall(server_name="concur", tool_name="health_check_concur"))
        assert result.success is True
        assert result.data["healthy"] is True


# ---------------------------------------------------------------------------
# Avalara — credential-gated
# ---------------------------------------------------------------------------


@_need_avalara
class TestAvalaraIntegration:
    def test_health_check_returns_healthy(self):
        result = call_tool(MCPToolCall(server_name="avalara", tool_name="health_check_avalara"))
        assert result.success is True
        assert result.data["healthy"] is True

    def test_combined_filing_check_live(self):
        result = call_tool(
            MCPToolCall(
                server_name="avalara",
                tool_name="check_combined_filing_states",
                arguments={"states": ["HI", "CA"]},
            )
        )
        assert result.success is True
        assert "HI" in result.data["combined"]


# ---------------------------------------------------------------------------
# Tango — credential-gated
# ---------------------------------------------------------------------------


@_need_tango
class TestTangoIntegration:
    def test_health_check_returns_healthy(self):
        result = call_tool(MCPToolCall(server_name="tango", tool_name="health_check_tango"))
        assert result.success is True
        assert result.data["healthy"] is True

    def test_validate_brand_no_credentials_needed(self):
        result = call_tool(
            MCPToolCall(
                server_name="tango",
                tool_name="validate_brand",
                arguments={"brand_name": "Amazon"},
            )
        )
        assert result.success is True
        assert result.data["approved"] is True
