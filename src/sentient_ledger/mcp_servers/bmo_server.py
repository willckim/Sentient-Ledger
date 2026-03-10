"""MCP server for BMO CSV processing.

BMO does not provide a public API, so this server processes CSV file content
directly.  It exposes 4 tools that wrap the existing ``bank_rec`` library.

The 5 known BMO description patterns
--------------------------------------
1. ELAVON CMS/ELAVON GES          → CC_MERCHANT_SETTLEMENT / CC_MERCHANT_FEE
2. AMEX                            → AMEX_SETTLEMENT
3. PAYMENTSTREAM / MONERIS / PAY   → PAYMENT_PROCESSING
4. PLAN FEE / FULL PLAN FEE REBATE → RETIREMENT_PLAN
5. SERVICE CHARGE / MONTHLY FEE    → BANK_FEE / BANK_FEE_REBATE
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from sentient_ledger.bank_rec.parser import parse_bmo_csv_string
from sentient_ledger.bank_rec.validator import classify_vendor, validate_bank_transactions
from sentient_ledger.bank_rec.mappings import VENDOR_PATTERNS

mcp = FastMCP("sentient-ledger-bmo")


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@mcp.tool()
def parse_bmo_csv(csv_content: str) -> dict:
    """Parse raw BMO CSV file content into structured rows.

    The CSV must be the daily BMO CAD account download format with the
    standard 8-column header.

    Args:
        csv_content: Full CSV file content as a string (BOM-safe).

    Returns:
        Dictionary with ``headers``, ``rows`` (list of dicts), ``total_rows``,
        and ``parse_errors`` (list of error strings).
    """
    result = parse_bmo_csv_string(csv_content)
    if result.df is None:
        return {
            "headers": result.headers,
            "rows": [],
            "total_rows": 0,
            "parse_errors": result.parse_errors,
        }
    rows = result.df.to_dict(orient="records")
    # Convert any non-string values to strings for JSON serialisation
    rows = [{k: str(v) for k, v in row.items()} for row in rows]
    return {
        "headers": result.headers,
        "rows": rows,
        "total_rows": result.total_rows,
        "parse_errors": result.parse_errors,
    }


@mcp.tool()
def classify_transactions(csv_content: str) -> dict:
    """Parse BMO CSV and classify each row by vendor category.

    Uses the ordered VENDOR_PATTERNS from ``bank_rec/mappings.py``
    (specific patterns take priority over generic ones).

    Args:
        csv_content: Full CSV file content as a string.

    Returns:
        Dictionary with ``rows`` list — each row gains a ``vendor_category``
        field — and ``category_counts`` summary.
    """
    result = parse_bmo_csv_string(csv_content)
    if result.df is None:
        return {"rows": [], "category_counts": {}, "parse_errors": result.parse_errors}

    rows = result.df.to_dict(orient="records")
    category_counts: dict[str, int] = {}
    enriched = []
    for row in rows:
        desc = str(row.get("Description", ""))
        category = classify_vendor(desc)
        row_out = {k: str(v) for k, v in row.items()}
        row_out["vendor_category"] = category
        enriched.append(row_out)
        category_counts[category] = category_counts.get(category, 0) + 1

    return {"rows": enriched, "category_counts": category_counts, "parse_errors": []}


@mcp.tool()
def get_unreconciled_transactions(csv_content: str) -> dict:
    """Filter BMO CSV rows to those not yet reconciled in Business Central.

    A row is considered unreconciled when the ``Bank Rec #`` column is empty.

    Args:
        csv_content: Full CSV file content as a string.

    Returns:
        Dictionary with ``rows`` (unreconciled), ``unreconciled_count``,
        and ``total_count``.
    """
    result = parse_bmo_csv_string(csv_content)
    if result.df is None:
        return {
            "rows": [],
            "unreconciled_count": 0,
            "total_count": 0,
            "parse_errors": result.parse_errors,
        }

    df = result.df
    bank_rec_col = "Bank Rec #"
    if bank_rec_col in df.columns:
        mask = df[bank_rec_col].isna() | (df[bank_rec_col].astype(str).str.strip() == "")
        unreconciled = df[mask]
    else:
        unreconciled = df  # no Bank Rec column → all rows are unreconciled

    rows = [{k: str(v) for k, v in row.items()} for row in unreconciled.to_dict(orient="records")]
    return {
        "rows": rows,
        "unreconciled_count": len(rows),
        "total_count": result.total_rows,
        "parse_errors": [],
    }


@mcp.tool()
def get_amex_transactions(csv_content: str, cutoff_date: str = "") -> dict:
    """Filter BMO CSV to AMEX settlement rows, optionally up to a cutoff date.

    Delegates to the existing ``reconcile_amex`` workflow (Workflow 3) for
    consistent filtering logic.

    Args:
        csv_content:  Full CSV file content as a string.
        cutoff_date:  Only include rows posted on or before this date
                      (``YYYY-MM-DD``).  Defaults to the previous business day.

    Returns:
        Dictionary with ``rows``, ``amex_count``, ``total_count``, and
        ``net_balance`` (sum of all AMEX amounts; should be zero if balanced).
    """
    from decimal import Decimal

    result = parse_bmo_csv_string(csv_content)
    if result.df is None:
        return {
            "rows": [],
            "amex_count": 0,
            "total_count": 0,
            "net_balance": "0",
            "parse_errors": result.parse_errors,
        }

    import pandas as pd
    from datetime import date

    df = result.df

    # Filter to AMEX rows using vendor classification on the raw DataFrame
    amex_mask = df["Description"].apply(
        lambda d: classify_vendor(str(d)) == "AMEX_SETTLEMENT"
    )
    df = df[amex_mask]

    if cutoff_date:
        try:
            cd = date.fromisoformat(cutoff_date)
        except ValueError:
            return {
                "rows": [],
                "amex_count": 0,
                "total_count": result.total_rows,
                "net_balance": "0",
                "parse_errors": [f"Invalid cutoff_date: {cutoff_date!r}"],
            }
        # Filter rows where Posted date <= cutoff
        posted_dates = pd.to_datetime(df["Posted"], format="mixed", dayfirst=False, errors="coerce")
        df = df[posted_dates.dt.date <= cd]

    # Compute net balance (Credit − Debit)
    net = Decimal("0")
    for _, row in df.iterrows():
        credit = row.get("Credit", "")
        debit = row.get("Debit", "")
        try:
            net += Decimal(str(credit)) if credit and str(credit) != "nan" else Decimal("0")
            net -= Decimal(str(debit)) if debit and str(debit) != "nan" else Decimal("0")
        except Exception:
            pass

    rows = [{k: str(v) for k, v in r.items()} for r in df.to_dict(orient="records")]
    return {
        "rows": rows,
        "amex_count": len(rows),
        "total_count": result.total_rows,
        "net_balance": str(net),
        "parse_errors": [],
    }


if __name__ == "__main__":
    mcp.run()
