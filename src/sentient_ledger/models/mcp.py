"""Pydantic models for MCP server layer."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field


class MCPServerConfig(BaseModel):
    """Configuration for a single MCP server."""

    name: str
    enabled: bool = True
    timeout_sec: float = 30.0
    max_retries: int = 3
    base_url: str = ""
    description: str = ""


class MCPToolCall(BaseModel):
    """A single tool invocation routed through the orchestrator."""

    server_name: str
    tool_name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    trace_id: str = ""


class MCPToolResult(BaseModel):
    """Result returned by a tool call."""

    success: bool
    data: Any = None
    error: str | None = None
    duration_ms: int = 0
    tool_call: MCPToolCall | None = None


class MCPHealthStatus(BaseModel):
    """Health snapshot for one MCP server."""

    server_name: str
    healthy: bool
    latency_ms: int = 0
    last_checked: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    error: str | None = None


class BCConnection(BaseModel):
    """Business Central connection parameters."""

    company_id: str
    tenant_id: str
    base_url: str
    environment: str = "production"
    client_id: str = ""


class SystemConnectionLog(BaseModel):
    """Audit log entry for an MCP server interaction."""

    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    server_name: str
    tool_name: str
    success: bool
    duration_ms: int = 0
    error: str | None = None
    trace_id: str = ""
    fallback_used: bool = False
