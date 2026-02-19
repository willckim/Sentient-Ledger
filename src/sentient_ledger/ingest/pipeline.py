"""Pipeline orchestrator — parse → map → validate → IngestionResult."""

from __future__ import annotations

from dataclasses import dataclass, field

from sentient_ledger.ingest.mapper import (
    map_depreciation_entry_row,
    map_fixed_asset_row,
    map_trial_balance_row,
)
from sentient_ledger.ingest.parser import parse_csv_file, parse_csv_string
from sentient_ledger.ingest.validator import (
    ValidationIssue,
    validate_depreciation_entries,
    validate_fixed_asset_records,
    validate_trial_balance_records,
)


@dataclass
class IngestionResult:
    """Final pipeline output, ready for graph state injection."""

    trial_balance_records: list[dict] = field(default_factory=list)
    asset_register: list[dict] = field(default_factory=list)
    depreciation_schedule: list[dict] = field(default_factory=list)
    total_rows: int = 0
    malformed_rows: int = 0
    malformed_pct: float = 0.0
    issues: list[ValidationIssue] = field(default_factory=list)

    def to_state_dict(self) -> dict:
        """Return the 6-key dict consumable by graph.invoke(state.update(...))."""
        return {
            "trial_balance_records": self.trial_balance_records,
            "asset_register": self.asset_register,
            "depreciation_schedule": self.depreciation_schedule,
            "total_rows": self.total_rows,
            "malformed_rows": self.malformed_rows,
            "malformed_pct": self.malformed_pct,
        }


def ingest_trial_balance(
    *,
    file_path: str | None = None,
    csv_content: str | None = None,
    ingestion_id: str = "",
) -> IngestionResult:
    """Ingest a D365 trial balance CSV → IngestionResult."""
    # Parse
    if csv_content is not None:
        parsed = parse_csv_string(csv_content)
    elif file_path is not None:
        parsed = parse_csv_file(file_path)
    else:
        raise ValueError("Either file_path or csv_content must be provided")

    result = IngestionResult(total_rows=parsed.total_rows)

    # Map
    mapped_records: list[dict] = []
    map_errors = 0
    for raw_row in parsed.rows:
        mr = map_trial_balance_row(raw_row, ingestion_id)
        if mr.record is not None:
            mapped_records.append(mr.record)
        if mr.errors:
            map_errors += 1
            for err in mr.errors:
                result.issues.append(
                    ValidationIssue(rule="mapping", severity="ERROR", message=err, row_index=-1)
                )

    # Validate
    vr = validate_trial_balance_records(mapped_records)
    result.trial_balance_records = vr.valid_records
    result.issues.extend(vr.issues)

    # Compute malformed
    result.malformed_rows = map_errors + vr.error_count
    result.malformed_pct = (
        (result.malformed_rows / result.total_rows * 100.0)
        if result.total_rows > 0
        else 0.0
    )

    return result


def ingest_fixed_assets(
    *,
    file_path: str | None = None,
    csv_content: str | None = None,
    ingestion_id: str = "",
) -> IngestionResult:
    """Ingest a D365 fixed assets CSV → IngestionResult."""
    # Parse
    if csv_content is not None:
        parsed = parse_csv_string(csv_content)
    elif file_path is not None:
        parsed = parse_csv_file(file_path)
    else:
        raise ValueError("Either file_path or csv_content must be provided")

    result = IngestionResult(total_rows=parsed.total_rows)

    # Map
    mapped_records: list[dict] = []
    map_errors = 0
    for raw_row in parsed.rows:
        mr = map_fixed_asset_row(raw_row, ingestion_id)
        if mr.record is not None:
            mapped_records.append(mr.record)
        if mr.errors:
            map_errors += 1
            for err in mr.errors:
                result.issues.append(
                    ValidationIssue(rule="mapping", severity="ERROR", message=err, row_index=-1)
                )

    # Validate
    vr = validate_fixed_asset_records(mapped_records)
    result.asset_register = vr.valid_records
    result.issues.extend(vr.issues)

    # Compute malformed
    result.malformed_rows = map_errors + vr.error_count
    result.malformed_pct = (
        (result.malformed_rows / result.total_rows * 100.0)
        if result.total_rows > 0
        else 0.0
    )

    return result


def ingest_depreciation_schedule(
    *,
    file_path: str | None = None,
    csv_content: str | None = None,
    ingestion_id: str = "",
) -> IngestionResult:
    """Ingest a D365 depreciation schedule CSV → IngestionResult."""
    if csv_content is not None:
        parsed = parse_csv_string(csv_content)
    elif file_path is not None:
        parsed = parse_csv_file(file_path)
    else:
        raise ValueError("Either file_path or csv_content must be provided")

    result = IngestionResult(total_rows=parsed.total_rows)

    # Map
    mapped_records: list[dict] = []
    map_errors = 0
    for raw_row in parsed.rows:
        mr = map_depreciation_entry_row(raw_row, ingestion_id)
        if mr.record is not None:
            mapped_records.append(mr.record)
        if mr.errors:
            map_errors += 1
            for err in mr.errors:
                result.issues.append(
                    ValidationIssue(rule="mapping", severity="ERROR", message=err, row_index=-1)
                )

    # Validate
    vr = validate_depreciation_entries(mapped_records)
    result.depreciation_schedule = vr.valid_records
    result.issues.extend(vr.issues)

    # Compute malformed
    result.malformed_rows = map_errors + vr.error_count
    result.malformed_pct = (
        (result.malformed_rows / result.total_rows * 100.0)
        if result.total_rows > 0
        else 0.0
    )

    return result


def ingest_d365_export(
    *,
    tb_path: str | None = None,
    fa_path: str | None = None,
    ds_path: str | None = None,
    tb_content: str | None = None,
    fa_content: str | None = None,
    ds_content: str | None = None,
    ingestion_id: str = "",
) -> IngestionResult:
    """Ingest TB, FA, and DS exports into a single IngestionResult."""
    combined = IngestionResult()

    if tb_path or tb_content:
        tb_result = ingest_trial_balance(
            file_path=tb_path, csv_content=tb_content, ingestion_id=ingestion_id
        )
        combined.trial_balance_records = tb_result.trial_balance_records
        combined.total_rows += tb_result.total_rows
        combined.malformed_rows += tb_result.malformed_rows
        combined.issues.extend(tb_result.issues)

    if fa_path or fa_content:
        fa_result = ingest_fixed_assets(
            file_path=fa_path, csv_content=fa_content, ingestion_id=ingestion_id
        )
        combined.asset_register = fa_result.asset_register
        combined.total_rows += fa_result.total_rows
        combined.malformed_rows += fa_result.malformed_rows
        combined.issues.extend(fa_result.issues)

    if ds_path or ds_content:
        ds_result = ingest_depreciation_schedule(
            file_path=ds_path, csv_content=ds_content, ingestion_id=ingestion_id
        )
        combined.depreciation_schedule = ds_result.depreciation_schedule
        combined.total_rows += ds_result.total_rows
        combined.malformed_rows += ds_result.malformed_rows
        combined.issues.extend(ds_result.issues)

    combined.malformed_pct = (
        (combined.malformed_rows / combined.total_rows * 100.0)
        if combined.total_rows > 0
        else 0.0
    )

    return combined
