"""Unit tests for the MCP orchestrator."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from sentient_ledger.models.mcp import MCPToolCall
from sentient_ledger.mcp_servers.orchestrator import (
    call_tool,
    call_tool_with_fallback,
    clear_connection_log,
    get_connection_log,
)

FIXTURES = Path(__file__).parent.parent.parent / "fixtures" / "bmo"
_CLEAN_CSV = (FIXTURES / "bmo_download_clean.csv").read_text(encoding="utf-8-sig")


@pytest.fixture(autouse=True)
def reset_log():
    """Clear the connection log before each test."""
    clear_connection_log()
    yield
    clear_connection_log()


class TestCallTool:
    def test_unknown_server_returns_failure(self):
        tc = MCPToolCall(server_name="nonexistent", tool_name="do_thing")
        result = call_tool(tc)
        assert result.success is False
        assert "Unknown tool" in result.error

    def test_unknown_tool_returns_failure(self):
        tc = MCPToolCall(server_name="bmo", tool_name="nonexistent_tool")
        result = call_tool(tc)
        assert result.success is False

    def test_bmo_parse_csv_success(self):
        tc = MCPToolCall(
            server_name="bmo",
            tool_name="parse_bmo_csv",
            arguments={"csv_content": _CLEAN_CSV},
        )
        result = call_tool(tc)
        assert result.success is True
        assert result.data["total_rows"] > 0

    def test_duration_ms_non_negative(self):
        tc = MCPToolCall(server_name="bmo", tool_name="parse_bmo_csv", arguments={"csv_content": _CLEAN_CSV})
        result = call_tool(tc)
        assert result.duration_ms >= 0

    def test_tool_call_attached_to_result(self):
        tc = MCPToolCall(server_name="bmo", tool_name="parse_bmo_csv", arguments={"csv_content": _CLEAN_CSV})
        result = call_tool(tc)
        assert result.tool_call is tc

    def test_filesystem_list_files(self, tmp_path, monkeypatch):
        monkeypatch.setenv("FS_DRIVE_ROOT", str(tmp_path))
        tc = MCPToolCall(server_name="filesystem", tool_name="list_files", arguments={"relative_dir": ""})
        result = call_tool(tc)
        assert result.success is True
        assert "files" in result.data


class TestConnectionLog:
    def test_successful_call_logged(self):
        tc = MCPToolCall(server_name="bmo", tool_name="parse_bmo_csv", arguments={"csv_content": _CLEAN_CSV})
        call_tool(tc)
        log = get_connection_log()
        assert len(log) == 1
        assert log[0].server_name == "bmo"
        assert log[0].success is True

    def test_failed_call_logged(self):
        tc = MCPToolCall(server_name="nonexistent", tool_name="do_thing")
        call_tool(tc)
        log = get_connection_log()
        assert len(log) == 1
        assert log[0].success is False
        assert log[0].error is not None

    def test_multiple_calls_all_logged(self):
        for _ in range(3):
            call_tool(MCPToolCall(server_name="bmo", tool_name="parse_bmo_csv", arguments={"csv_content": _CLEAN_CSV}))
        assert len(get_connection_log()) == 3

    def test_trace_id_preserved_in_log(self):
        tc = MCPToolCall(server_name="bmo", tool_name="parse_bmo_csv", arguments={"csv_content": _CLEAN_CSV}, trace_id="trace-xyz")
        call_tool(tc)
        log = get_connection_log()
        assert log[0].trace_id == "trace-xyz"


class TestCallToolWithFallback:
    def test_primary_success_no_fallback_called(self):
        fallback_called = []

        def fallback():
            fallback_called.append(True)
            return {"fallback": True}

        tc = MCPToolCall(server_name="bmo", tool_name="parse_bmo_csv", arguments={"csv_content": _CLEAN_CSV})
        result = call_tool_with_fallback(tc, fallback_fn=fallback)
        assert result.success is True
        assert fallback_called == []

    def test_primary_failure_triggers_fallback(self):
        def fallback():
            return {"fallback": "data"}

        tc = MCPToolCall(server_name="nonexistent", tool_name="do_thing")
        result = call_tool_with_fallback(tc, fallback_fn=fallback)
        assert result.success is True
        assert result.data == {"fallback": "data"}

    def test_fallback_flag_set_in_log(self):
        def fallback():
            return {"ok": True}

        tc = MCPToolCall(server_name="nonexistent", tool_name="do_thing")
        call_tool_with_fallback(tc, fallback_fn=fallback)
        log = get_connection_log()
        fallback_entry = [e for e in log if e.fallback_used]
        assert len(fallback_entry) >= 1

    def test_no_fallback_fn_returns_failure(self):
        tc = MCPToolCall(server_name="nonexistent", tool_name="do_thing")
        result = call_tool_with_fallback(tc, fallback_fn=None)
        assert result.success is False

    def test_both_primary_and_fallback_fail(self):
        def bad_fallback():
            raise RuntimeError("fallback also broken")

        tc = MCPToolCall(server_name="nonexistent", tool_name="do_thing")
        result = call_tool_with_fallback(tc, fallback_fn=bad_fallback)
        assert result.success is False
        assert "fallback also broken" in result.error
