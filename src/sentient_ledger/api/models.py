"""Pydantic v2 request/response models for the Sentient Ledger REST API."""

from __future__ import annotations

from pydantic import BaseModel


class ValidationSummary(BaseModel):
    """Condensed view of a BankRecValidationResult for the API response."""

    error_count: int
    warning_count: int
    issue_rules: list[str]  # deduplicated rule names that fired
    new_rows: int
    total_rows: int


class WorkflowResponse(BaseModel):
    """Unified response envelope for all four bank-rec workflow endpoints.

    The frontend should inspect ``status`` first:
      "ok"      — safe to import into BC, no flags
      "warning" — soft flags present, review recommended
      "error"   — hard errors, do not import until resolved

    ``output_csv_b64`` is the BC-ready import file, base64-encoded.
    The frontend decodes it and offers a download link.  Using base64 in the
    response body avoids the need for file storage infrastructure.  Upgrade to
    a presigned S3 URL pattern later without changing the endpoint signature.
    """

    run_id: str
    workflow: str
    status: str  # "ok" | "warning" | "error"
    timestamp: str
    user_id: str

    input_file_hash: str
    output_file_hash: str | None = None
    output_csv_b64: str | None = None  # base64-encoded BC import CSV
    output_filename: str | None = None  # suggested Save As filename

    validation: ValidationSummary

    # Hashes of the per-batch AuditRecord objects created during this run.
    # Cross-references the proposal audit chain inside the audit log.
    audit_chain: list[str]

    # Hash of the RunRecord written to runs.jsonl.
    # The frontend can display this as a run fingerprint.
    run_hash: str
