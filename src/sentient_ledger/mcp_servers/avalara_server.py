"""MCP server for Avalara AvaTax REST API.

Provides 6 tools for tax calculation, transaction management, nexus queries,
and filing calendar retrieval.  Combined-filing states are flagged automatically.

Environment variables
---------------------
AVALARA_ACCOUNT_ID   Numeric account ID
AVALARA_LICENSE_KEY  License key (used for HTTP Basic auth)
AVALARA_BASE_URL     https://rest.avatax.com/api/v2
AVALARA_COMPANY_CODE Company code registered in AvaTax (e.g. ``OMPI``)
"""

from __future__ import annotations

import base64
import os
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP

from sentient_ledger.config import AVALARA_COMBINED_FILING_STATES

mcp = FastMCP("sentient-ledger-avalara")

# ---------------------------------------------------------------------------
# Auth (HTTP Basic)
# ---------------------------------------------------------------------------


def _avatax_headers() -> dict[str, str]:
    account_id = os.environ.get("AVALARA_ACCOUNT_ID", "")
    license_key = os.environ.get("AVALARA_LICENSE_KEY", "")
    if not account_id or not license_key:
        raise RuntimeError("AVALARA_ACCOUNT_ID and AVALARA_LICENSE_KEY must be set.")
    creds = base64.b64encode(f"{account_id}:{license_key}".encode()).decode()
    return {
        "Authorization": f"Basic {creds}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


def _base() -> str:
    return os.environ.get("AVALARA_BASE_URL", "https://rest.avatax.com/api/v2")


def _company_code() -> str:
    return os.environ.get("AVALARA_COMPANY_CODE", "OMPI")


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@mcp.tool()
def calculate_tax(
    amount: float,
    ship_from_state: str,
    ship_to_state: str,
    ship_to_zip: str,
    description: str = "",
    customer_code: str = "DEFAULT",
) -> dict:
    """Calculate sales tax for a transaction.

    Args:
        amount:          Sale amount in USD.
        ship_from_state: Two-letter origin state code (e.g. ``"IL"``).
        ship_to_state:   Two-letter destination state code.
        ship_to_zip:     Destination ZIP code.
        description:     Line item description (optional).
        customer_code:   Customer code in AvaTax (default ``"DEFAULT"``).

    Returns:
        Dictionary with ``total_tax``, ``total_taxable``, and ``lines``.
    """
    try:
        body: dict[str, Any] = {
            "type": "SalesOrder",
            "companyCode": _company_code(),
            "customerCode": customer_code,
            "addresses": {
                "shipFrom": {"region": ship_from_state, "country": "US"},
                "shipTo": {"region": ship_to_state, "postalCode": ship_to_zip, "country": "US"},
            },
            "lines": [
                {
                    "number": "1",
                    "quantity": 1,
                    "amount": amount,
                    "description": description,
                }
            ],
        }
        resp = httpx.post(
            f"{_base()}/transactions/create",
            headers=_avatax_headers(),
            json=body,
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        return {
            "total_tax": data.get("totalTax"),
            "total_taxable": data.get("totalTaxable"),
            "total_amount": data.get("totalAmount"),
            "lines": data.get("lines", []),
        }
    except Exception as exc:
        return {"total_tax": None, "error": str(exc)}


@mcp.tool()
def commit_transaction(transaction_code: str) -> dict:
    """Commit a previously calculated tax transaction.

    A committed transaction is locked for reporting purposes.

    Args:
        transaction_code: The ``code`` returned by a prior ``calculate_tax`` call.

    Returns:
        Dictionary with ``committed`` (bool) and ``transaction_code``.
    """
    try:
        resp = httpx.post(
            f"{_base()}/companies/{_company_code()}/transactions/{transaction_code}/commit",
            headers=_avatax_headers(),
            json={"commit": True},
            timeout=30,
        )
        resp.raise_for_status()
        return {"committed": True, "transaction_code": transaction_code}
    except Exception as exc:
        return {"committed": False, "error": str(exc)}


@mcp.tool()
def list_nexus(country: str = "US") -> dict:
    """List nexus jurisdictions registered for the company.

    Args:
        country: ISO 2-letter country code (default ``"US"``).

    Returns:
        Dictionary with ``nexus`` list (state, jurisName, nexusType).
    """
    try:
        params = {"$filter": f"country eq '{country}'", "companyCode": _company_code()}
        resp = httpx.get(
            f"{_base()}/companies/{_company_code()}/nexus",
            headers=_avatax_headers(),
            params=params,
            timeout=30,
        )
        resp.raise_for_status()
        items = resp.json().get("value", [])
        return {
            "nexus": [
                {
                    "state": n.get("region"),
                    "jurisName": n.get("jurisName"),
                    "nexusType": n.get("nexusTypeId"),
                }
                for n in items
            ],
            "count": len(items),
        }
    except Exception as exc:
        return {"nexus": [], "count": 0, "error": str(exc)}


@mcp.tool()
def get_filing_calendar(year: int, month: int) -> dict:
    """Retrieve the tax filing calendar for a given period.

    Args:
        year:  Calendar year (e.g. 2026).
        month: Calendar month 1–12.

    Returns:
        Dictionary with ``filings`` list and ``period``.
    """
    try:
        params = {
            "companyCode": _company_code(),
            "$filter": f"year eq {year} and month eq {month}",
        }
        resp = httpx.get(
            f"{_base()}/companies/{_company_code()}/filingcalendars",
            headers=_avatax_headers(),
            params=params,
            timeout=30,
        )
        resp.raise_for_status()
        filings = resp.json().get("value", [])
        return {
            "filings": filings,
            "count": len(filings),
            "period": f"{year}-{month:02d}",
        }
    except Exception as exc:
        return {"filings": [], "count": 0, "error": str(exc)}


@mcp.tool()
def check_combined_filing_states(states: list[str]) -> dict:
    """Check which of the given states use combined filing.

    Combined-filing states (HI IA MO NM OH SC TN UT WA) file as a group; they
    cannot be filed individually.

    Args:
        states: List of two-letter state codes to check.

    Returns:
        Dictionary with ``combined`` (states that require combined filing) and
        ``individual`` (states that can be filed individually).
    """
    upper = [s.upper() for s in states]
    combined = [s for s in upper if s in AVALARA_COMBINED_FILING_STATES]
    individual = [s for s in upper if s not in AVALARA_COMBINED_FILING_STATES]
    return {
        "combined": combined,
        "individual": individual,
        "combined_filing_states": sorted(AVALARA_COMBINED_FILING_STATES),
    }


@mcp.tool()
def health_check_avalara() -> dict:
    """Verify connectivity to Avalara AvaTax.

    Returns:
        Dictionary with ``healthy`` (bool) and ``latency_ms``.
    """
    import time as _time

    start = _time.perf_counter()
    try:
        resp = httpx.get(
            f"{_base()}/utilities/ping",
            headers=_avatax_headers(),
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
