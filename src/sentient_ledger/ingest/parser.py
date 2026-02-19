"""CSV parser for D365 exports — stdlib csv, no pandas."""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field


@dataclass
class ParseResult:
    """Result of parsing a CSV file/string into raw rows."""

    rows: list[dict[str, str]] = field(default_factory=list)
    headers: list[str] = field(default_factory=list)
    total_rows: int = 0
    parse_errors: list[str] = field(default_factory=list)


def _strip_bom(text: str) -> str:
    """Remove UTF-8 BOM if present."""
    if text.startswith("\ufeff"):
        return text[1:]
    return text


def _parse(reader: csv.DictReader) -> ParseResult:
    """Shared parsing logic for file and string paths."""
    result = ParseResult()
    result.headers = list(reader.fieldnames or [])
    for i, raw_row in enumerate(reader):
        # Skip completely empty rows (values may be str, None, or list from extra cols)
        named_values = [v for k, v in raw_row.items() if k is not None]
        if all(
            v is None or (isinstance(v, str) and v.strip() == "")
            for v in named_values
        ):
            continue
        # Trim whitespace from keys and values; replace None with "", skip None keys
        row = {
            k.strip(): (v.strip() if isinstance(v, str) else ("" if v is None else v))
            for k, v in raw_row.items()
            if k is not None
        }
        result.rows.append(row)
        result.total_rows += 1
    return result


def parse_csv_string(content: str) -> ParseResult:
    """Parse CSV content from an in-memory string."""
    content = _strip_bom(content)
    reader = csv.DictReader(io.StringIO(content))
    return _parse(reader)


def parse_csv_file(path: str) -> ParseResult:
    """Parse a CSV file from disk."""
    try:
        with open(path, newline="", encoding="utf-8-sig") as fh:
            reader = csv.DictReader(fh)
            return _parse(reader)
    except FileNotFoundError:
        result = ParseResult()
        result.parse_errors.append(f"File not found: {path}")
        return result
    except Exception as exc:  # noqa: BLE001
        result = ParseResult()
        result.parse_errors.append(f"Parse error: {exc}")
        return result
