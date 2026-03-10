"""MCP server for SAP Concur REST API.

Provides 5 tools for expense report retrieval and approval, focused on the
OMPI-EXP pay group used by Ortho Molecular Products.

Environment variables
---------------------
CONCUR_CLIENT_ID      Concur app client ID
CONCUR_CLIENT_SECRET  Concur app client secret
CONCUR_BASE_URL       https://us.api.concursolutions.com
CONCUR_REFRESH_TOKEN  OAuth 2.0 refresh token (user-granted)
"""

from __future__ import annotations

import os
import time
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP

from sentient_ledger.config import CONCUR_PAY_GROUP

mcp = FastMCP("sentient-ledger-concur")

# ---------------------------------------------------------------------------
# Token manager
# ---------------------------------------------------------------------------

_token_cache: dict[str, Any] = {}


def _get_access_token() -> str:
    """Refresh OAuth 2.0 token using the stored refresh token."""
    cached = _token_cache.get("concur")
    if cached and cached["expires_at"] > time.time() + 60:
        return cached["access_token"]

    base_url = os.environ.get("CONCUR_BASE_URL", "https://us.api.concursolutions.com")
    resp = httpx.post(
        f"{base_url}/oauth2/v0/token",
        data={
            "grant_type": "refresh_token",
            "client_id": os.environ.get("CONCUR_CLIENT_ID", ""),
            "client_secret": os.environ.get("CONCUR_CLIENT_SECRET", ""),
            "refresh_token": os.environ.get("CONCUR_REFRESH_TOKEN", ""),
        },
        timeout=30,
    )
    resp.raise_for_status()
    payload = resp.json()
    _token_cache["concur"] = {
        "access_token": payload["access_token"],
        "expires_at": time.time() + int(payload.get("expires_in", 3600)),
    }
    return payload["access_token"]


def _concur_headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {_get_access_token()}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


def _base() -> str:
    return os.environ.get("CONCUR_BASE_URL", "https://us.api.concursolutions.com")


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@mcp.tool()
def get_expense_reports(
    pay_group: str = CONCUR_PAY_GROUP,
    status: str = "PENDING_PAYMENT",
    limit: int = 50,
) -> dict:
    """Fetch expense reports from Concur, filtered by pay group and status.

    Args:
        pay_group: Pay group code (default ``OMPI-EXP``).
        status:    Report status filter (default ``PENDING_PAYMENT``).
        limit:     Maximum number of reports to return (default 50).

    Returns:
        Dictionary with ``reports`` list and ``count``.
    """
    try:
        params = {
            "paymentType": pay_group,
            "approvalStatus": status,
            "limit": limit,
        }
        resp = httpx.get(
            f"{_base()}/api/v3.0/expense/reports",
            headers=_concur_headers(),
            params=params,
            timeout=30,
        )
        resp.raise_for_status()
        items = resp.json().get("Items", [])
        return {"reports": items, "count": len(items)}
    except Exception as exc:
        return {"reports": [], "count": 0, "error": str(exc)}


@mcp.tool()
def approve_expense_report(report_id: str, comment: str = "") -> dict:
    """Approve an expense report in Concur.

    Args:
        report_id: Concur report ID.
        comment:   Optional approval comment.

    Returns:
        Dictionary with ``approved`` (bool).
    """
    try:
        resp = httpx.patch(
            f"{_base()}/api/v3.0/expense/reports/{report_id}/approve",
            headers=_concur_headers(),
            json={"comment": comment},
            timeout=30,
        )
        resp.raise_for_status()
        return {"approved": True, "report_id": report_id}
    except Exception as exc:
        return {"approved": False, "error": str(exc)}


@mcp.tool()
def get_payment_batches(pay_group: str = CONCUR_PAY_GROUP, status: str = "") -> dict:
    """Fetch payment batch status for a pay group.

    Args:
        pay_group: Pay group code (default ``OMPI-EXP``).
        status:    Optional batch status filter (e.g. ``"PROCESSING"``).

    Returns:
        Dictionary with ``batches`` list and ``count``.
    """
    try:
        params: dict[str, Any] = {"paymentTypeCode": pay_group}
        if status:
            params["batchStatus"] = status
        resp = httpx.get(
            f"{_base()}/api/v3.0/expense/paymentbatches",
            headers=_concur_headers(),
            params=params,
            timeout=30,
        )
        resp.raise_for_status()
        items = resp.json().get("Items", [])
        return {"batches": items, "count": len(items)}
    except Exception as exc:
        return {"batches": [], "count": 0, "error": str(exc)}


@mcp.tool()
def get_employees(pay_group: str = CONCUR_PAY_GROUP, limit: int = 200) -> dict:
    """List employees associated with a pay group.

    Args:
        pay_group: Pay group code (default ``OMPI-EXP``).
        limit:     Maximum number of employees to return (default 200).

    Returns:
        Dictionary with ``employees`` list and ``count``.
    """
    try:
        params = {"customData12": pay_group, "limit": limit}
        resp = httpx.get(
            f"{_base()}/api/v3.0/common/users",
            headers=_concur_headers(),
            params=params,
            timeout=30,
        )
        resp.raise_for_status()
        items = resp.json().get("Items", [])
        return {"employees": items, "count": len(items)}
    except Exception as exc:
        return {"employees": [], "count": 0, "error": str(exc)}


@mcp.tool()
def health_check_concur() -> dict:
    """Verify connectivity to SAP Concur.

    Returns:
        Dictionary with ``healthy`` (bool) and ``latency_ms``.
    """
    import time as _time

    start = _time.perf_counter()
    try:
        resp = httpx.get(
            f"{_base()}/api/v3.0/expense/reports",
            headers=_concur_headers(),
            params={"limit": 1},
            timeout=10,
        )
        resp.raise_for_status()
        latency_ms = int((_time.perf_counter() - start) * 1000)
        return {"healthy": True, "latency_ms": latency_ms}
    except Exception as exc:
        latency_ms = int((_time.perf_counter() - start) * 1000)
        return {"healthy": False, "latency_ms": latency_ms, "error": str(exc)}


if __name__ == "__main__":
    mcp.run()
