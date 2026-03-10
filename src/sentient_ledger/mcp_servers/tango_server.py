"""MCP server for Tango Card RaaS (Rewards as a Service) API.

Provides 6 tools for reward catalog browsing, account management, brand
validation, and order placement.  ``place_order`` enforces the approved-brand
list defined in ``config.py`` before sending any request to Tango.

Environment variables
---------------------
TANGO_PLATFORM_NAME  Platform name from Tango portal
TANGO_PLATFORM_KEY   Platform key (used for HTTP Basic auth)
TANGO_BASE_URL       https://api.tangocard.com/raas/v2
TANGO_ACCOUNT_ID     Account identifier
TANGO_CUSTOMER_ID    Customer identifier
"""

from __future__ import annotations

import base64
import os
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP

from sentient_ledger.config import TANGO_APPROVED_BRANDS

mcp = FastMCP("sentient-ledger-tango")

# ---------------------------------------------------------------------------
# Auth (HTTP Basic with platform credentials)
# ---------------------------------------------------------------------------


def _tango_headers() -> dict[str, str]:
    platform_name = os.environ.get("TANGO_PLATFORM_NAME", "")
    platform_key = os.environ.get("TANGO_PLATFORM_KEY", "")
    if not platform_name or not platform_key:
        raise RuntimeError("TANGO_PLATFORM_NAME and TANGO_PLATFORM_KEY must be set.")
    creds = base64.b64encode(f"{platform_name}:{platform_key}".encode()).decode()
    return {
        "Authorization": f"Basic {creds}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


def _base() -> str:
    return os.environ.get("TANGO_BASE_URL", "https://api.tangocard.com/raas/v2")


def _account_id() -> str:
    return os.environ.get("TANGO_ACCOUNT_ID", "")


def _customer_id() -> str:
    return os.environ.get("TANGO_CUSTOMER_ID", "")


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@mcp.tool()
def list_catalog(country_code: str = "US", currency_code: str = "USD") -> dict:
    """List available reward brands in the Tango catalog.

    Args:
        country_code:  ISO 3166-1 alpha-2 country code (default ``"US"``).
        currency_code: ISO 4217 currency code (default ``"USD"``).

    Returns:
        Dictionary with ``brands`` list (utid, brandName, minValue, maxValue)
        and ``count``.
    """
    try:
        params = {"country": country_code, "currency": currency_code}
        resp = httpx.get(
            f"{_base()}/catalogs",
            headers=_tango_headers(),
            params=params,
            timeout=30,
        )
        resp.raise_for_status()
        brands = resp.json().get("brands", [])
        simplified = [
            {
                "utid": b.get("utid"),
                "brandName": b.get("brandName"),
                "minValue": b.get("minValue"),
                "maxValue": b.get("maxValue"),
                "currencyCode": b.get("currencyCode"),
                "approved": b.get("brandName", "") in TANGO_APPROVED_BRANDS,
            }
            for b in brands
        ]
        return {"brands": simplified, "count": len(simplified)}
    except Exception as exc:
        return {"brands": [], "count": 0, "error": str(exc)}


@mcp.tool()
def get_account_balance() -> dict:
    """Retrieve the current Tango account balance.

    Returns:
        Dictionary with ``balance`` (USD), ``accountId``, and ``currentBalance``.
    """
    try:
        account_id = _account_id()
        customer_id = _customer_id()
        if not account_id or not customer_id:
            return {"balance": None, "error": "TANGO_ACCOUNT_ID and TANGO_CUSTOMER_ID must be set."}

        resp = httpx.get(
            f"{_base()}/accounts/{account_id}",
            headers=_tango_headers(),
            params={"customerIdentifier": customer_id},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        return {
            "balance": data.get("currentBalance"),
            "accountId": data.get("accountIdentifier"),
            "currencyCode": data.get("currencyCode", "USD"),
        }
    except Exception as exc:
        return {"balance": None, "error": str(exc)}


@mcp.tool()
def validate_brand(brand_name: str) -> dict:
    """Check if a reward brand is in the approved list.

    This is a pure local check — no network call required.

    Args:
        brand_name: Display name of the brand (e.g. ``"Amazon"``).

    Returns:
        Dictionary with ``approved`` (bool) and ``approved_brands`` list.
    """
    return {
        "brand_name": brand_name,
        "approved": brand_name in TANGO_APPROVED_BRANDS,
        "approved_brands": sorted(TANGO_APPROVED_BRANDS),
    }


@mcp.tool()
def place_order(
    brand_name: str,
    utid: str,
    amount: float,
    recipient_email: str,
    recipient_name: str,
    sender_name: str = "Ortho Molecular Products",
    notes: str = "",
) -> dict:
    """Place a reward order with Tango Card.

    Enforces the approved-brand list: orders for unapproved brands are rejected
    before any API call is made.

    Args:
        brand_name:      Display name of the brand (must be in approved list).
        utid:            Tango catalog UTID (unique identifier for the reward).
        amount:          Reward value in USD.
        recipient_email: Email address of the recipient.
        recipient_name:  Full name of the recipient.
        sender_name:     Sender display name (default ``"Ortho Molecular Products"``).
        notes:           Optional notes for the recipient.

    Returns:
        Dictionary with ``order_id``, ``status``, and ``estimated_delivery``.
    """
    # Guard: brand must be in approved list
    if brand_name not in TANGO_APPROVED_BRANDS:
        return {
            "order_id": None,
            "status": "rejected",
            "error": (
                f"Brand {brand_name!r} is not in the approved list. "
                f"Approved brands: {sorted(TANGO_APPROVED_BRANDS)}"
            ),
        }

    try:
        account_id = _account_id()
        customer_id = _customer_id()
        body: dict[str, Any] = {
            "accountIdentifier": account_id,
            "customerIdentifier": customer_id,
            "amount": amount,
            "utid": utid,
            "recipient": {
                "email": recipient_email,
                "firstName": recipient_name.split()[0] if recipient_name else "",
                "lastName": " ".join(recipient_name.split()[1:]) if len(recipient_name.split()) > 1 else "",
            },
            "sender": {"name": sender_name},
            "notes": notes,
        }
        resp = httpx.post(
            f"{_base()}/orders",
            headers=_tango_headers(),
            json=body,
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        return {
            "order_id": data.get("referenceOrderID"),
            "status": data.get("status", "submitted"),
            "estimated_delivery": data.get("estimatedDelivery", ""),
        }
    except Exception as exc:
        return {"order_id": None, "status": "error", "error": str(exc)}


@mcp.tool()
def get_order_status(order_id: str) -> dict:
    """Retrieve the status of a previously placed reward order.

    Args:
        order_id: Tango ``referenceOrderID`` returned by ``place_order``.

    Returns:
        Dictionary with ``status``, ``delivered_at``, and ``recipient_email``.
    """
    try:
        resp = httpx.get(
            f"{_base()}/orders/{order_id}",
            headers=_tango_headers(),
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        return {
            "order_id": order_id,
            "status": data.get("status"),
            "delivered_at": data.get("deliveredAt", ""),
            "recipient_email": data.get("recipient", {}).get("email", ""),
            "amount": data.get("amount"),
        }
    except Exception as exc:
        return {"order_id": order_id, "status": "unknown", "error": str(exc)}


@mcp.tool()
def health_check_tango() -> dict:
    """Verify connectivity to Tango Card RaaS.

    Returns:
        Dictionary with ``healthy`` (bool) and ``latency_ms``.
    """
    import time as _time

    start = _time.perf_counter()
    try:
        resp = httpx.get(
            f"{_base()}/catalogs",
            headers=_tango_headers(),
            params={"country": "US", "currency": "USD"},
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
