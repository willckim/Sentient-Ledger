"""Adapter layer — converts P3 canonical records to detector-compatible flat dicts."""

from __future__ import annotations

from decimal import Decimal


def is_canonical_format(record: dict) -> bool:
    """Return True if record uses nested canonical format (has 'identity' key)."""
    return "identity" in record


def canonical_asset_to_detector(record: dict) -> dict:
    """Flatten a CanonicalAssetRecord dict to ScenarioAssetRecord-compatible dict."""
    identity = record.get("identity", {})
    acquisition = record.get("acquisition", {})
    current_state = record.get("current_state", {})

    return {
        "asset_id": identity.get("asset_id", ""),
        "group": identity.get("group", "PP&E"),
        "description": identity.get("description", ""),
        "acquisition_date": acquisition.get("date", ""),
        "cost": acquisition.get("cost", Decimal("0")),
        "salvage_value": acquisition.get("salvage_value", Decimal("0")),
        "useful_life_months": acquisition.get("useful_life_months", 0),
        "depreciation_method": acquisition.get("method", "STRAIGHT_LINE"),
        "convention": acquisition.get("convention", "FULL_MONTH"),
        "status": current_state.get("status", "ACTIVE"),
        "entity_id": "ENTITY-001",
        "disposal_date": None,
        "disposal_proceeds": None,
    }


def tb_records_to_gl_balances(records: list[dict]) -> list[dict]:
    """Extract GLBalance-compatible dicts from canonical TB records."""
    gl_balances: list[dict] = []
    for rec in records:
        account = rec.get("account", {})
        period = rec.get("period", {})
        balances = rec.get("balances", {})
        dimensions = rec.get("dimensions", {})

        gl_balances.append({
            "account_code": account.get("code", ""),
            "account_name": account.get("name", ""),
            "period": period.get("calendar_month", ""),
            "balance": balances.get("closing", Decimal("0")),
            "entity_id": dimensions.get("business_unit", "ENTITY-001") or "ENTITY-001",
        })
    return gl_balances


def adapt_state_for_detector(state_dict: dict) -> dict:
    """Convert an ingestion state dict so it is consumable by the detector path.

    - Flattens nested asset_register records (only if canonical format).
    - Derives gl_balances from trial_balance_records.
    - Passes through depreciation_schedule unchanged.
    """
    result = dict(state_dict)

    # Convert asset_register if needed
    raw_register = result.get("asset_register", [])
    if raw_register and is_canonical_format(raw_register[0]):
        result["asset_register"] = [
            canonical_asset_to_detector(r) for r in raw_register
        ]

    # Derive GL balances from TB records
    tb_records = result.get("trial_balance_records", [])
    if tb_records:
        result["gl_balances"] = tb_records_to_gl_balances(tb_records)

    # depreciation_schedule passes through unchanged
    if "depreciation_schedule" not in result:
        result["depreciation_schedule"] = []

    return result
