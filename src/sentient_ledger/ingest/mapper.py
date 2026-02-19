"""Column mapper — translates raw D365 dicts to canonical structures."""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

import re

from sentient_ledger.ingest.mappings import (
    ASSET_STATUS_MAP,
    DEPRECIATION_CONVENTION_MAP,
    DEPRECIATION_METHOD_MAP,
    DS_COLUMN_MAP,
    DS_DECIMAL_FIELDS,
    DS_REQUIRED_COLUMNS,
    FA_COLUMN_MAP,
    FA_DECIMAL_FIELDS,
    FA_INTEGER_FIELDS,
    FA_REQUIRED_COLUMNS,
    TB_COLUMN_MAP,
    TB_DECIMAL_FIELDS,
    TB_REQUIRED_COLUMNS,
)


@dataclass
class MapResult:
    """Result of mapping a single raw row."""

    record: dict | None = None
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_ACCOUNT_CATEGORY_MAP: dict[str, str] = {
    "1": "ASSET",
    "2": "LIABILITY",
    "3": "EQUITY",
    "4": "REVENUE",
}


def _account_category_heuristic(code: str) -> str:
    """Derive account category from the first digit of the account code."""
    if code and code[0] in _ACCOUNT_CATEGORY_MAP:
        return _ACCOUNT_CATEGORY_MAP[code[0]]
    return "EXPENSE"


def _row_hash(raw: dict) -> str:
    """SHA-256 hash of the raw row for integrity tracking."""
    canonical = json.dumps(raw, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


def _coerce_decimal(value: str, field_name: str) -> tuple[Decimal | None, str | None]:
    """Try to coerce a string to Decimal. Returns (value, error_or_None)."""
    if value == "":
        return Decimal("0"), None
    try:
        return Decimal(value), None
    except InvalidOperation:
        return None, f"Cannot convert '{field_name}' value '{value}' to Decimal"


def _coerce_int(value: str, field_name: str) -> tuple[int | None, str | None]:
    """Try to coerce a string to int."""
    if value == "":
        return 0, None
    try:
        return int(value), None
    except ValueError:
        return None, f"Cannot convert '{field_name}' value '{value}' to integer"


def _fiscal_year_from_month(calendar_month: str) -> int:
    """Extract fiscal year from 'YYYY-MM' string."""
    try:
        return int(calendar_month.split("-")[0])
    except (ValueError, IndexError):
        return 0


def _fiscal_period_from_month(calendar_month: str) -> int:
    """Extract fiscal period (month number) from 'YYYY-MM' string."""
    try:
        return int(calendar_month.split("-")[1])
    except (ValueError, IndexError):
        return 0


# ---------------------------------------------------------------------------
# Trial Balance mapper
# ---------------------------------------------------------------------------

def map_trial_balance_row(raw: dict, ingestion_id: str = "") -> MapResult:
    """Map a single raw TB row to canonical structure."""
    result = MapResult()

    # Check required columns
    missing = TB_REQUIRED_COLUMNS - set(raw.keys())
    if missing:
        result.errors.append(f"Missing required columns: {sorted(missing)}")
        return result

    # Check non-empty required values
    for col in TB_REQUIRED_COLUMNS:
        if raw.get(col, "").strip() == "":
            result.errors.append(f"Required column '{col}' is empty")
            return result

    # Coerce decimals
    decimals: dict[str, Decimal] = {}
    for col in TB_DECIMAL_FIELDS:
        val = raw.get(col, "")
        dec, err = _coerce_decimal(val, col)
        if err:
            result.errors.append(err)
            return result
        decimals[col] = dec  # type: ignore[assignment]

    # Computed fields
    calendar_month = raw["CalendarMonth"]
    opening = decimals["OpeningBalance"]
    debits = decimals["Debits"]
    credits = decimals["Credits"]
    closing = decimals["ClosingBalance"]
    movement = debits - credits

    account_code = raw["MainAccount"]
    category = _account_category_heuristic(account_code)

    balance_verified = (opening + debits - credits) == closing

    record: dict = {
        "record_id": str(uuid.uuid4()),
        "source": "DYNAMICS_365",
        "ingestion_id": ingestion_id,
        "account": {
            "code": account_code,
            "name": raw["AccountName"],
            "category": category,
            "sub_category": "",
            "is_control_account": False,
        },
        "dimensions": {
            "business_unit": raw["BusinessUnit"],
            "department": raw.get("Department", None),
            "cost_center": raw.get("CostCenter", None),
            "composite_key": f"{account_code}-{raw['BusinessUnit']}",
        },
        "balances": {
            "opening": opening,
            "debits": debits,
            "credits": credits,
            "closing": closing,
            "movement": movement,
        },
        "currency": {
            "transaction": raw.get("TransactionCurrency", "USD"),
            "reporting": raw.get("ReportingCurrency", "USD"),
            "exchange_rate": decimals.get("ExchangeRate"),
        },
        "period": {
            "fiscal_year": _fiscal_year_from_month(calendar_month),
            "fiscal_period": _fiscal_period_from_month(calendar_month),
            "calendar_month": calendar_month,
        },
        "integrity": {
            "source_row_hash": _row_hash(raw),
            "balance_verified": balance_verified,
        },
    }

    result.record = record
    return result


# ---------------------------------------------------------------------------
# Fixed Asset mapper
# ---------------------------------------------------------------------------

def map_fixed_asset_row(raw: dict, ingestion_id: str = "") -> MapResult:
    """Map a single raw FA row to canonical structure."""
    result = MapResult()

    # Check required columns
    missing = FA_REQUIRED_COLUMNS - set(raw.keys())
    if missing:
        result.errors.append(f"Missing required columns: {sorted(missing)}")
        return result

    # Check non-empty required values
    for col in FA_REQUIRED_COLUMNS:
        if raw.get(col, "").strip() == "":
            result.errors.append(f"Required column '{col}' is empty")
            return result

    # Coerce decimals
    decimals: dict[str, Decimal] = {}
    for col in FA_DECIMAL_FIELDS:
        val = raw.get(col, "")
        dec, err = _coerce_decimal(val, col)
        if err:
            result.errors.append(err)
            return result
        decimals[col] = dec  # type: ignore[assignment]

    # Coerce integers
    integers: dict[str, int] = {}
    for col in FA_INTEGER_FIELDS:
        val = raw.get(col, "")
        ival, err = _coerce_int(val, col)
        if err:
            result.errors.append(err)
            return result
        integers[col] = ival  # type: ignore[assignment]

    # Enum translations
    method_raw = raw["DepreciationMethod"]
    method = DEPRECIATION_METHOD_MAP.get(method_raw)
    if method is None:
        result.errors.append(
            f"Unknown depreciation method '{method_raw}'. "
            f"Expected one of: {sorted(DEPRECIATION_METHOD_MAP.keys())}"
        )
        return result

    convention_raw = raw.get("Convention", "")
    if convention_raw:
        convention = DEPRECIATION_CONVENTION_MAP.get(convention_raw)
        if convention is None:
            result.errors.append(
                f"Unknown depreciation convention '{convention_raw}'. "
                f"Expected one of: {sorted(DEPRECIATION_CONVENTION_MAP.keys())}"
            )
            return result
    else:
        convention = "FULL_MONTH"  # default

    status_raw = raw["Status"]
    status = ASSET_STATUS_MAP.get(status_raw)
    if status is None:
        result.errors.append(
            f"Unknown asset status '{status_raw}'. "
            f"Expected one of: {sorted(ASSET_STATUS_MAP.keys())}"
        )
        return result

    # ServiceLifeUnit: if "Years", multiply by 12
    service_life = integers["ServiceLife"]
    service_life_unit = raw.get("ServiceLifeUnit", "").strip()
    if service_life_unit.lower() == "years":
        service_life = service_life * 12

    # Computed fields
    cost = decimals["AcquisitionCost"]
    salvage = decimals["SalvageValue"]
    accum_dep = decimals["AccumulatedDepreciation"]
    nbv = decimals["NetBookValue"]

    depreciable_base = cost - salvage
    nbv_verified = (cost - accum_dep) == nbv

    remaining_life = max(0, service_life - int(accum_dep / depreciable_base * service_life)) if depreciable_base > 0 else 0

    record: dict = {
        "record_id": str(uuid.uuid4()),
        "source": "DYNAMICS_365",
        "ingestion_id": ingestion_id,
        "identity": {
            "asset_id": raw["AssetId"],
            "group": raw["AssetGroup"],
            "description": raw["Description"],
        },
        "acquisition": {
            "date": raw["AcquisitionDate"],
            "cost": cost,
            "method": method,
            "useful_life_months": service_life,
            "salvage_value": salvage,
            "depreciable_base": depreciable_base,
            "convention": convention,
        },
        "current_state": {
            "accumulated_depreciation": accum_dep,
            "net_book_value": nbv,
            "nbv_verified": nbv_verified,
            "status": status,
            "last_depreciation_date": None,
            "remaining_life_months": remaining_life,
        },
        "integrity": {
            "source_row_hash": _row_hash(raw),
        },
    }

    result.record = record
    return result


# ---------------------------------------------------------------------------
# Depreciation Schedule mapper
# ---------------------------------------------------------------------------

_PERIOD_RE = re.compile(r"^\d{4}-\d{2}$")


def map_depreciation_entry_row(raw: dict, ingestion_id: str = "") -> MapResult:
    """Map a single raw depreciation schedule row to flat dict."""
    result = MapResult()

    # Check required columns
    missing = DS_REQUIRED_COLUMNS - set(raw.keys())
    if missing:
        result.errors.append(f"Missing required columns: {sorted(missing)}")
        return result

    # Check non-empty required values
    for col in DS_REQUIRED_COLUMNS:
        if raw.get(col, "").strip() == "":
            result.errors.append(f"Required column '{col}' is empty")
            return result

    # Validate period format
    period = raw["Period"].strip()
    if not _PERIOD_RE.match(period):
        result.errors.append(f"Invalid period format '{period}', expected YYYY-MM")
        return result

    # Coerce decimals
    decimals: dict[str, Decimal] = {}
    for col in DS_DECIMAL_FIELDS:
        val = raw.get(col, "")
        dec, err = _coerce_decimal(val, col)
        if err:
            result.errors.append(err)
            return result
        decimals[col] = dec  # type: ignore[assignment]

    result.record = {
        "asset_id": raw["AssetId"].strip(),
        "period": period,
        "amount": decimals["DepreciationAmount"],
        "accumulated": decimals["AccumulatedDepreciation"],
        "net_book_value": decimals["NetBookValue"],
    }
    return result
