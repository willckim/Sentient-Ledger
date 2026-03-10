"""MCP server for Business Central REST API.

Provides 8 tools covering G/L entries, bank accounts, fixed assets, trial
balance, journal posting, and connectivity.  OAuth 2.0 tokens are fetched via
Azure AD client-credentials flow and cached in-process until expiry.

Environment variables
---------------------
BC_TENANT_ID        Azure AD tenant GUID
BC_CLIENT_ID        Azure AD app registration client ID
BC_CLIENT_SECRET    Azure AD app registration client secret
BC_BASE_URL         e.g. https://api.businesscentral.dynamics.com/v2.0
BC_ENVIRONMENT      production | sandbox  (default: production)
BC_COMPANY_ID_ORTHO GUID for Ortho Molecular Products company
BC_COMPANY_ID_UTZY  GUID for Utzy Naturals company
"""

from __future__ import annotations

import os
import time
from decimal import Decimal
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("sentient-ledger-bc")

# ---------------------------------------------------------------------------
# Token manager (in-process cache, no external state)
# ---------------------------------------------------------------------------

_token_cache: dict[str, Any] = {}


def _get_access_token() -> str:
    """Fetch (or return cached) OAuth 2.0 bearer token from Azure AD."""
    tenant_id = os.environ.get("BC_TENANT_ID", "")
    client_id = os.environ.get("BC_CLIENT_ID", "")
    client_secret = os.environ.get("BC_CLIENT_SECRET", "")

    if not all([tenant_id, client_id, client_secret]):
        raise RuntimeError(
            "BC_TENANT_ID, BC_CLIENT_ID, and BC_CLIENT_SECRET must be set."
        )

    # Return cached token if still valid (with 60 s buffer)
    cached = _token_cache.get("bc")
    if cached and cached["expires_at"] > time.time() + 60:
        return cached["access_token"]

    url = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
    resp = httpx.post(
        url,
        data={
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": client_secret,
            "scope": "https://api.businesscentral.dynamics.com/.default",
        },
        timeout=30,
    )
    resp.raise_for_status()
    payload = resp.json()
    _token_cache["bc"] = {
        "access_token": payload["access_token"],
        "expires_at": time.time() + int(payload.get("expires_in", 3600)),
    }
    return payload["access_token"]


def _bc_headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {_get_access_token()}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


def _company_url(company: str) -> str:
    """Build the per-company base URL."""
    base = os.environ.get("BC_BASE_URL", "https://api.businesscentral.dynamics.com/v2.0")
    env = os.environ.get("BC_ENVIRONMENT", "production")
    key = f"BC_COMPANY_ID_{company.upper()}"
    company_id = os.environ.get(key, "")
    if not company_id:
        raise RuntimeError(f"Environment variable {key} is not set.")
    return f"{base}/{env}/api/v2.0/companies({company_id})"


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@mcp.tool()
def get_companies() -> dict:
    """List all companies accessible in Business Central.

    Returns:
        Dictionary with ``companies`` list (id, name, displayName).
    """
    try:
        base = os.environ.get("BC_BASE_URL", "https://api.businesscentral.dynamics.com/v2.0")
        env = os.environ.get("BC_ENVIRONMENT", "production")
        url = f"{base}/{env}/api/v2.0/companies"
        resp = httpx.get(url, headers=_bc_headers(), timeout=30)
        resp.raise_for_status()
        data = resp.json().get("value", [])
        return {"companies": [{"id": c["id"], "name": c["name"], "displayName": c.get("displayName", "")} for c in data]}
    except Exception as exc:
        return {"companies": [], "error": str(exc)}


@mcp.tool()
def get_gl_entries(
    company: str,
    account_no: str,
    date_from: str = "",
    date_to: str = "",
    top: int = 100,
) -> dict:
    """Fetch G/L entries for a specific account.

    Args:
        company:    Company key — ``ortho`` or ``utzy``.
        account_no: G/L account number (e.g. ``"11105"``).
        date_from:  Start date filter YYYY-MM-DD (optional).
        date_to:    End date filter YYYY-MM-DD (optional).
        top:        Maximum entries to return (default 100).

    Returns:
        Dictionary with ``entries`` list and ``count``.
    """
    try:
        base = _company_url(company)
        filters = [f"accountNumber eq '{account_no}'"]
        if date_from:
            filters.append(f"postingDate ge {date_from}")
        if date_to:
            filters.append(f"postingDate le {date_to}")
        params: dict[str, Any] = {"$filter": " and ".join(filters), "$top": top}
        resp = httpx.get(f"{base}/generalLedgerEntries", headers=_bc_headers(), params=params, timeout=30)
        resp.raise_for_status()
        entries = resp.json().get("value", [])
        return {"entries": entries, "count": len(entries)}
    except Exception as exc:
        return {"entries": [], "count": 0, "error": str(exc)}


@mcp.tool()
def get_bank_account_balance(company: str, bank_account_no: str) -> dict:
    """Get the current balance and details of a bank account in BC.

    Args:
        company:         Company key — ``ortho`` or ``utzy``.
        bank_account_no: Bank account number (e.g. ``"BMO-CAD"``).

    Returns:
        Dictionary with ``balance``, ``currencyCode``, and ``lastStatementBalance``.
    """
    try:
        base = _company_url(company)
        params = {"$filter": f"number eq '{bank_account_no}'"}
        resp = httpx.get(f"{base}/bankAccounts", headers=_bc_headers(), params=params, timeout=30)
        resp.raise_for_status()
        accounts = resp.json().get("value", [])
        if not accounts:
            return {"balance": None, "error": f"Bank account {bank_account_no!r} not found"}
        acct = accounts[0]
        return {
            "balance": acct.get("balance"),
            "currencyCode": acct.get("currencyCode"),
            "lastStatementBalance": acct.get("lastStatementBalance"),
            "number": acct.get("number"),
            "name": acct.get("name"),
        }
    except Exception as exc:
        return {"balance": None, "error": str(exc)}


@mcp.tool()
def get_trial_balance(company: str, date_from: str = "", date_to: str = "") -> dict:
    """Fetch the trial balance for a company.

    Args:
        company:   Company key — ``ortho`` or ``utzy``.
        date_from: Period start date YYYY-MM-DD (optional).
        date_to:   Period end date YYYY-MM-DD (optional).

    Returns:
        Dictionary with ``accounts`` list (no, name, debit, credit, netChange).
    """
    try:
        base = _company_url(company)
        params: dict[str, Any] = {}
        filters = []
        if date_from:
            filters.append(f"dateFilter ge {date_from}")
        if date_to:
            filters.append(f"dateFilter le {date_to}")
        if filters:
            params["$filter"] = " and ".join(filters)
        resp = httpx.get(f"{base}/trialBalance", headers=_bc_headers(), params=params, timeout=30)
        resp.raise_for_status()
        accounts = resp.json().get("value", [])
        return {"accounts": accounts, "count": len(accounts)}
    except Exception as exc:
        return {"accounts": [], "count": 0, "error": str(exc)}


@mcp.tool()
def get_fixed_assets(company: str, status: str = "") -> dict:
    """List fixed assets for a company.

    Args:
        company: Company key — ``ortho`` or ``utzy``.
        status:  Filter by status (e.g. ``"Active"``).  Empty returns all.

    Returns:
        Dictionary with ``assets`` list and ``count``.
    """
    try:
        base = _company_url(company)
        params: dict[str, Any] = {}
        if status:
            params["$filter"] = f"status eq '{status}'"
        resp = httpx.get(f"{base}/fixedAssets", headers=_bc_headers(), params=params, timeout=30)
        resp.raise_for_status()
        assets = resp.json().get("value", [])
        return {"assets": assets, "count": len(assets)}
    except Exception as exc:
        return {"assets": [], "count": 0, "error": str(exc)}


@mcp.tool()
def post_bank_rec_lines(company: str, bank_account_no: str, lines: list[dict]) -> dict:
    """Post Bank Account Reconciliation lines to Business Central.

    Enforces the BC rule: the reconciliation balance must be zero before
    posting.  Each line must include ``transactionDate``, ``description``, and
    ``statementAmount``.

    Args:
        company:         Company key — ``ortho`` or ``utzy``.
        bank_account_no: Target bank account number.
        lines:           List of reconciliation line dicts.

    Returns:
        Dictionary with ``posted`` (bool) and ``statement_no`` if successful.
    """
    try:
        # Balance-zero guard
        total = sum(Decimal(str(ln.get("statementAmount", 0))) for ln in lines)
        if total != Decimal("0"):
            return {
                "posted": False,
                "error": f"Balance must be zero before posting. Current net: {total}",
            }

        base = _company_url(company)
        # Create a bank reconciliation header
        header_resp = httpx.post(
            f"{base}/bankAccountReconciliations",
            headers=_bc_headers(),
            json={"bankAccountNumber": bank_account_no},
            timeout=30,
        )
        header_resp.raise_for_status()
        header = header_resp.json()
        rec_id = header["id"]
        statement_no = header.get("statementNumber", "")

        # Post lines
        for line in lines:
            line_resp = httpx.post(
                f"{base}/bankAccountReconciliations({rec_id})/bankAccountReconciliationLines",
                headers=_bc_headers(),
                json=line,
                timeout=30,
            )
            line_resp.raise_for_status()

        return {"posted": True, "statement_no": statement_no, "reconciliation_id": rec_id}
    except Exception as exc:
        return {"posted": False, "error": str(exc)}


@mcp.tool()
def post_journal_entries(company: str, journal_batch: str, lines: list[dict]) -> dict:
    """Post Cash Receipt Journal (or General Journal) lines to BC.

    Args:
        company:       Company key — ``ortho`` or ``utzy``.
        journal_batch: Journal batch name (e.g. ``"CCAMEX"``).
        lines:         List of journal line dicts matching BC import format.

    Returns:
        Dictionary with ``posted`` (bool) and ``line_count``.
    """
    try:
        base = _company_url(company)
        posted = 0
        for line in lines:
            resp = httpx.post(
                f"{base}/journals(journalBatchName='{journal_batch}')/journalLines",
                headers=_bc_headers(),
                json=line,
                timeout=30,
            )
            resp.raise_for_status()
            posted += 1

        # Post the batch
        post_resp = httpx.post(
            f"{base}/journals(journalBatchName='{journal_batch}')/Microsoft.NAV.post",
            headers=_bc_headers(),
            timeout=30,
        )
        post_resp.raise_for_status()

        return {"posted": True, "line_count": posted}
    except Exception as exc:
        return {"posted": False, "line_count": 0, "error": str(exc)}


@mcp.tool()
def health_check_bc() -> dict:
    """Verify connectivity to Business Central.

    Returns:
        Dictionary with ``healthy`` (bool) and ``latency_ms``.
    """
    import time as _time

    start = _time.perf_counter()
    try:
        base = os.environ.get("BC_BASE_URL", "https://api.businesscentral.dynamics.com/v2.0")
        env = os.environ.get("BC_ENVIRONMENT", "production")
        resp = httpx.get(
            f"{base}/{env}/api/v2.0/companies",
            headers=_bc_headers(),
            timeout=10,
        )
        resp.raise_for_status()
        latency_ms = int((time.perf_counter() - start) * 1000)
        return {"healthy": True, "latency_ms": latency_ms}
    except Exception as exc:
        latency_ms = int((time.perf_counter() - start) * 1000)
        return {"healthy": False, "latency_ms": latency_ms, "error": str(exc)}


if __name__ == "__main__":
    mcp.run()
