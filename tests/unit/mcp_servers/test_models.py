"""Unit tests for MCP Pydantic models."""

from __future__ import annotations

from sentient_ledger.models.mcp import (
    BCConnection,
    MCPHealthStatus,
    MCPServerConfig,
    MCPToolCall,
    MCPToolResult,
    SystemConnectionLog,
)


class TestMCPServerConfig:
    def test_defaults(self):
        cfg = MCPServerConfig(name="test")
        assert cfg.enabled is True
        assert cfg.timeout_sec == 30.0
        assert cfg.max_retries == 3

    def test_custom_values(self):
        cfg = MCPServerConfig(name="bc", enabled=False, timeout_sec=10.0, max_retries=1)
        assert cfg.name == "bc"
        assert cfg.enabled is False
        assert cfg.timeout_sec == 10.0

    def test_serialises_to_json(self):
        import json
        cfg = MCPServerConfig(name="avalara", description="Tax server")
        data = json.loads(cfg.model_dump_json())
        assert data["name"] == "avalara"
        assert data["description"] == "Tax server"


class TestMCPToolCall:
    def test_basic_fields(self):
        tc = MCPToolCall(server_name="bmo", tool_name="parse_bmo_csv", arguments={"csv_content": "a,b"})
        assert tc.server_name == "bmo"
        assert tc.tool_name == "parse_bmo_csv"
        assert tc.arguments["csv_content"] == "a,b"

    def test_empty_trace_id_default(self):
        tc = MCPToolCall(server_name="bc", tool_name="get_companies")
        assert tc.trace_id == ""

    def test_with_trace_id(self):
        tc = MCPToolCall(server_name="bc", tool_name="get_companies", trace_id="abc-123")
        assert tc.trace_id == "abc-123"


class TestMCPToolResult:
    def test_success_result(self):
        r = MCPToolResult(success=True, data={"foo": "bar"}, duration_ms=42)
        assert r.success is True
        assert r.data["foo"] == "bar"
        assert r.duration_ms == 42
        assert r.error is None

    def test_failure_result(self):
        r = MCPToolResult(success=False, error="connection refused")
        assert r.success is False
        assert r.error == "connection refused"
        assert r.data is None

    def test_tool_call_attached(self):
        tc = MCPToolCall(server_name="bc", tool_name="get_companies")
        r = MCPToolResult(success=True, tool_call=tc)
        assert r.tool_call.server_name == "bc"


class TestMCPHealthStatus:
    def test_healthy(self):
        h = MCPHealthStatus(server_name="bc", healthy=True, latency_ms=55)
        assert h.healthy is True
        assert h.latency_ms == 55
        assert h.error is None

    def test_unhealthy_with_error(self):
        h = MCPHealthStatus(server_name="concur", healthy=False, error="timeout")
        assert h.healthy is False
        assert h.error == "timeout"

    def test_last_checked_populated(self):
        h = MCPHealthStatus(server_name="tango", healthy=True)
        assert h.last_checked != ""


class TestBCConnection:
    def test_fields(self):
        bc = BCConnection(
            company_id="guid-ortho",
            tenant_id="guid-tenant",
            base_url="https://api.businesscentral.dynamics.com/v2.0",
        )
        assert bc.company_id == "guid-ortho"
        assert bc.environment == "production"


class TestSystemConnectionLog:
    def test_success_log(self):
        log = SystemConnectionLog(server_name="bmo", tool_name="parse_bmo_csv", success=True)
        assert log.success is True
        assert log.fallback_used is False
        assert log.timestamp != ""

    def test_fallback_flag(self):
        log = SystemConnectionLog(
            server_name="bc", tool_name="get_gl_entries", success=True, fallback_used=True
        )
        assert log.fallback_used is True

    def test_error_log(self):
        log = SystemConnectionLog(
            server_name="avalara", tool_name="calculate_tax", success=False, error="401 Unauthorized"
        )
        assert log.error == "401 Unauthorized"
