"""Pandas-based BMO CSV parser.

Separate from the existing ingest/parser.py (stdlib csv) because the bank rec
module needs DataFrame column operations (filtering, merging, balance recalc).
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path

import pandas as pd

from sentient_ledger.bank_rec.mappings import BMO_DECIMAL_FIELDS, BMO_REQUIRED_COLUMNS


@dataclass
class BankParseResult:
    df: pd.DataFrame | None = None
    headers: list[str] = field(default_factory=list)
    total_rows: int = 0
    parse_errors: list[str] = field(default_factory=list)


def _clean_decimal_column(series: pd.Series) -> pd.Series:
    """Coerce a string series to Decimal, replacing blanks/NaN with None."""

    def _coerce(val: object) -> Decimal | None:
        if pd.isna(val) or str(val).strip() == "":
            return None
        try:
            cleaned = str(val).strip().replace(",", "")
            return Decimal(cleaned)
        except InvalidOperation:
            return None

    return series.map(_coerce)


def parse_bmo_csv_string(content: str) -> BankParseResult:
    """Parse a BMO CSV string (UTF-8 or UTF-8-BOM) into a BankParseResult."""
    result = BankParseResult()

    # Strip BOM if present
    content = content.lstrip("\ufeff")

    if not content.strip():
        result.parse_errors.append("Empty CSV content")
        return result

    try:
        df = pd.read_csv(io.StringIO(content), dtype=str, keep_default_na=False)
    except Exception as exc:  # noqa: BLE001
        result.parse_errors.append(f"CSV parse error: {exc}")
        return result

    # Trim whitespace from column names and string values
    df.columns = [c.strip() for c in df.columns]
    for col in df.columns:
        df[col] = df[col].str.strip()

    # Drop fully empty rows
    df = df.dropna(how="all")
    df = df[~(df == "").all(axis=1)]

    result.headers = list(df.columns)

    # Validate required columns
    missing = BMO_REQUIRED_COLUMNS - set(df.columns)
    if missing:
        result.parse_errors.append(f"Missing required columns: {sorted(missing)}")
        return result

    # Coerce decimal columns
    for col in BMO_DECIMAL_FIELDS:
        if col in df.columns:
            df[col] = _clean_decimal_column(df[col])

    result.df = df.reset_index(drop=True)
    result.total_rows = len(df)
    return result


def parse_bmo_csv_file(path: str | Path) -> BankParseResult:
    """Parse a BMO CSV file from disk."""
    try:
        content = Path(path).read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        result = BankParseResult()
        result.parse_errors.append(f"File not found: {path}")
        return result
    except Exception as exc:  # noqa: BLE001
        result = BankParseResult()
        result.parse_errors.append(f"File read error: {exc}")
        return result

    return parse_bmo_csv_string(content)
