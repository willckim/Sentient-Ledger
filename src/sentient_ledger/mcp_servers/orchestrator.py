"""MCP Orchestrator — routes tool calls and handles graceful degradation.

Architecture
------------
The orchestrator is the single entry point for all MCP tool calls.  It:

1. Inspects the ``server_name`` field on an ``MCPToolCall`` to route the call.
2. Invokes the correct server's tool function (in-process, no network hop for
   local tools like ``bmo_server`` and ``file_system_server``).
3. On failure, logs the error and optionally falls back to the file-ingest
   pipeline (for BMO and file-system tools where a fallback exists).
4. Records every interaction as a ``SystemConnectionLog`` entry.

Supported server names
-----------------------
- ``filesystem``  → file_system_server tools
- ``bc``          → bc_server tools
- ``concur``      → concur_server tools
- ``avalara``     → avalara_server tools
- ``tango``       → tango_server tools
- ``bmo``         → bmo_server tools (CSV-only, no live API)
"""

from __future__ import annotations

import time
from typing import Any

from sentient_ledger.models.mcp import (
    MCPHealthStatus,
    MCPToolCall,
    MCPToolResult,
    SystemConnectionLog,
)


# ---------------------------------------------------------------------------
# Tool registry — maps (server_name, tool_name) → callable
# ---------------------------------------------------------------------------

def _build_registry() -> dict[tuple[str, str], Any]:
    from sentient_ledger.mcp_servers import (
        file_system_server,
        bc_server,
        concur_server,
        avalara_server,
        tango_server,
        bmo_server,
    )

    return {
        # file system
        ("filesystem", "list_files"): file_system_server.list_files,
        ("filesystem", "read_csv"): file_system_server.read_csv,
        ("filesystem", "read_excel"): file_system_server.read_excel,
        ("filesystem", "write_csv"): file_system_server.write_csv,
        ("filesystem", "file_exists"): file_system_server.file_exists,
        ("filesystem", "get_latest_file"): file_system_server.get_latest_file,
        # bc
        ("bc", "get_companies"): bc_server.get_companies,
        ("bc", "get_gl_entries"): bc_server.get_gl_entries,
        ("bc", "get_bank_account_balance"): bc_server.get_bank_account_balance,
        ("bc", "get_trial_balance"): bc_server.get_trial_balance,
        ("bc", "get_fixed_assets"): bc_server.get_fixed_assets,
        ("bc", "post_bank_rec_lines"): bc_server.post_bank_rec_lines,
        ("bc", "post_journal_entries"): bc_server.post_journal_entries,
        ("bc", "health_check_bc"): bc_server.health_check_bc,
        # concur
        ("concur", "get_expense_reports"): concur_server.get_expense_reports,
        ("concur", "approve_expense_report"): concur_server.approve_expense_report,
        ("concur", "get_payment_batches"): concur_server.get_payment_batches,
        ("concur", "get_employees"): concur_server.get_employees,
        ("concur", "health_check_concur"): concur_server.health_check_concur,
        # avalara
        ("avalara", "calculate_tax"): avalara_server.calculate_tax,
        ("avalara", "commit_transaction"): avalara_server.commit_transaction,
        ("avalara", "list_nexus"): avalara_server.list_nexus,
        ("avalara", "get_filing_calendar"): avalara_server.get_filing_calendar,
        ("avalara", "check_combined_filing_states"): avalara_server.check_combined_filing_states,
        ("avalara", "health_check_avalara"): avalara_server.health_check_avalara,
        # tango
        ("tango", "list_catalog"): tango_server.list_catalog,
        ("tango", "get_account_balance"): tango_server.get_account_balance,
        ("tango", "validate_brand"): tango_server.validate_brand,
        ("tango", "place_order"): tango_server.place_order,
        ("tango", "get_order_status"): tango_server.get_order_status,
        ("tango", "health_check_tango"): tango_server.health_check_tango,
        # bmo
        ("bmo", "parse_bmo_csv"): bmo_server.parse_bmo_csv,
        ("bmo", "classify_transactions"): bmo_server.classify_transactions,
        ("bmo", "get_unreconciled_transactions"): bmo_server.get_unreconciled_transactions,
        ("bmo", "get_amex_transactions"): bmo_server.get_amex_transactions,
    }


_REGISTRY: dict[tuple[str, str], Any] | None = None
_connection_log: list[SystemConnectionLog] = []


def _registry() -> dict[tuple[str, str], Any]:
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = _build_registry()
    return _REGISTRY


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def call_tool(tool_call: MCPToolCall) -> MCPToolResult:
    """Route and invoke a tool call.

    On any exception the result has ``success=False`` and ``error`` set.
    No exception propagates to the caller.

    Args:
        tool_call: ``MCPToolCall`` specifying server, tool, and arguments.

    Returns:
        ``MCPToolResult`` with result data or error details.
    """
    key = (tool_call.server_name, tool_call.tool_name)
    fn = _registry().get(key)

    t0 = time.perf_counter()
    if fn is None:
        duration_ms = int((time.perf_counter() - t0) * 1000)
        err = f"Unknown tool: {tool_call.server_name}/{tool_call.tool_name}"
        _log(tool_call, success=False, duration_ms=duration_ms, error=err)
        return MCPToolResult(
            success=False,
            error=err,
            duration_ms=duration_ms,
            tool_call=tool_call,
        )

    try:
        data = fn(**tool_call.arguments)
        duration_ms = int((time.perf_counter() - t0) * 1000)
        _log(tool_call, success=True, duration_ms=duration_ms)
        return MCPToolResult(
            success=True,
            data=data,
            duration_ms=duration_ms,
            tool_call=tool_call,
        )
    except Exception as exc:
        duration_ms = int((time.perf_counter() - t0) * 1000)
        _log(tool_call, success=False, duration_ms=duration_ms, error=str(exc))
        return MCPToolResult(
            success=False,
            error=str(exc),
            duration_ms=duration_ms,
            tool_call=tool_call,
        )


def call_tool_with_fallback(
    tool_call: MCPToolCall,
    fallback_fn: Any | None = None,
    fallback_kwargs: dict | None = None,
) -> MCPToolResult:
    """Invoke a tool with optional fallback on failure.

    If the primary tool call fails and ``fallback_fn`` is provided, the
    fallback is called with ``fallback_kwargs``.  The result's ``data`` will
    contain the fallback output.  ``SystemConnectionLog.fallback_used`` is set
    to ``True`` in that case.

    Args:
        tool_call:       Primary tool call to attempt.
        fallback_fn:     Callable to invoke on primary failure (optional).
        fallback_kwargs: Keyword arguments for the fallback callable.

    Returns:
        ``MCPToolResult`` — either primary result or fallback result.
    """
    result = call_tool(tool_call)
    if result.success:
        return result

    if fallback_fn is None:
        return result

    # Primary failed — try fallback
    t0 = time.perf_counter()
    try:
        data = fallback_fn(**(fallback_kwargs or {}))
        duration_ms = int((time.perf_counter() - t0) * 1000)
        _log(tool_call, success=True, duration_ms=duration_ms, fallback_used=True)
        return MCPToolResult(
            success=True,
            data=data,
            duration_ms=duration_ms,
            tool_call=tool_call,
        )
    except Exception as exc:
        duration_ms = int((time.perf_counter() - t0) * 1000)
        _log(tool_call, success=False, duration_ms=duration_ms, error=str(exc), fallback_used=True)
        return MCPToolResult(
            success=False,
            error=f"Primary and fallback both failed. Fallback error: {exc}",
            duration_ms=duration_ms,
            tool_call=tool_call,
        )


def health_check_all() -> list[MCPHealthStatus]:
    """Run health checks against all live external servers.

    Local-only servers (``bmo``, ``filesystem``) are not included as they
    require no network connectivity.

    Returns:
        List of ``MCPHealthStatus`` — one per external server.
    """
    health_calls = [
        MCPToolCall(server_name="bc", tool_name="health_check_bc"),
        MCPToolCall(server_name="concur", tool_name="health_check_concur"),
        MCPToolCall(server_name="avalara", tool_name="health_check_avalara"),
        MCPToolCall(server_name="tango", tool_name="health_check_tango"),
    ]
    statuses: list[MCPHealthStatus] = []
    for tc in health_calls:
        result = call_tool(tc)
        data = result.data or {}
        statuses.append(
            MCPHealthStatus(
                server_name=tc.server_name,
                healthy=result.success and data.get("healthy", False),
                latency_ms=data.get("latency_ms", result.duration_ms),
                error=result.error or data.get("error"),
            )
        )
    return statuses


def get_connection_log() -> list[SystemConnectionLog]:
    """Return a copy of the in-process connection log."""
    return list(_connection_log)


def clear_connection_log() -> None:
    """Clear the in-process connection log (useful for testing)."""
    _connection_log.clear()


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _log(
    tool_call: MCPToolCall,
    *,
    success: bool,
    duration_ms: int,
    error: str | None = None,
    fallback_used: bool = False,
) -> None:
    _connection_log.append(
        SystemConnectionLog(
            server_name=tool_call.server_name,
            tool_name=tool_call.tool_name,
            success=success,
            duration_ms=duration_ms,
            error=error,
            trace_id=tool_call.trace_id,
            fallback_used=fallback_used,
        )
    )
