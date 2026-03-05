"""Bank reconciliation workflow endpoints.

Four endpoints expose the four bank_rec workflows as HTTP POST routes.
Each endpoint:
  1. Reads the uploaded BMO CSV file (or xlsx for Workflow 1)
  2. Runs the corresponding workflow function
  3. Base64-encodes the output CSV for the frontend to download
  4. Logs a RunRecord (with SHA-256 hash chain) to runs.jsonl
  5. Returns a WorkflowResponse JSON with run metadata + output

Why ``def`` not ``async def``
------------------------------
FastAPI automatically runs ``def`` endpoints in a threadpool.  The workflow
functions are synchronous (pandas, stdlib csv) and do real I/O.  Using
``def`` is the correct FastAPI pattern for CPU/IO-bound sync code; using
``async def`` would block the event loop.  File reads use ``file.file.read()``
(the underlying SpooledTemporaryFile), which is synchronous and correct inside
``def`` endpoints.

Auth readiness
--------------
``user_id = Depends(get_current_user)`` appears in every endpoint signature.
Adding OAuth2/JWT later means changing only ``get_current_user`` in
dependencies.py — zero route changes needed.
"""

from __future__ import annotations

import base64
import hashlib
import io
import tempfile
import time
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

import pandas as pd
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from sentient_ledger.api.dependencies import get_current_user, get_run_logger
from sentient_ledger.api.models import ValidationSummary, WorkflowResponse
from sentient_ledger.api.run_logger import RunLogger, RunRecord, new_run_id
from sentient_ledger.bank_rec import (
    export_cash_receipt_journal,
    post_new_lines,
    reconcile_amex,
    reconcile_gl,
)
from sentient_ledger.models.enums import BankRecWorkflow

router = APIRouter()


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _encode_output(path: Path) -> tuple[str | None, str | None]:
    """Read a file and return (base64_string, sha256_hash), or (None, None)."""
    if not path.exists():
        return None, None
    content = path.read_bytes()
    return base64.b64encode(content).decode(), _sha256(content)


def _parse_decimal(value: str, field_name: str) -> Decimal:
    try:
        return Decimal(value.strip())
    except InvalidOperation:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid decimal for '{field_name}': {value!r}",
        )


def _parse_optional_decimal(value: str) -> Decimal | None:
    v = value.strip()
    if not v:
        return None
    try:
        return Decimal(v)
    except InvalidOperation:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid decimal value: {value!r}",
        )


def _parse_optional_date(value: str) -> date | None:
    v = value.strip()
    if not v:
        return None
    try:
        return date.fromisoformat(v)
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid date '{value!r}'. Expected YYYY-MM-DD.",
        )


def _run_status(errors: int, warnings: int) -> str:
    if errors > 0:
        return "error"
    if warnings > 0:
        return "warning"
    return "ok"


def _build_and_log(
    *,
    run_logger: RunLogger,
    workflow: BankRecWorkflow,
    user_id: str,
    input_file_name: str | None,
    input_hash: str,
    output_hash: str | None,
    output_b64: str | None,
    output_filename: str | None,
    errors: int,
    warnings: int,
    issue_rules: list[str],
    new_rows: int,
    total_rows: int,
    audits: list[dict],
    duration_ms: int,
) -> WorkflowResponse:
    """Build WorkflowResponse, write RunRecord to JSONL, return response."""
    from sentient_ledger.agents.base import now_iso

    status = _run_status(errors, warnings)
    record = RunRecord(
        run_id=new_run_id(),
        workflow=workflow,
        timestamp=now_iso(),
        user_id=user_id,
        input_file_name=input_file_name,
        input_file_hash=input_hash,
        output_file_hash=output_hash,
        status=status,
        error_count=errors,
        warning_count=warnings,
        new_rows=new_rows,
        total_rows=total_rows,
        audit_record_hashes=[a["integrity"]["record_hash"] for a in audits],
        duration_ms=duration_ms,
    )
    logged = run_logger.log(record)

    return WorkflowResponse(
        run_id=logged.run_id,
        workflow=workflow.value,
        status=status,
        timestamp=logged.timestamp,
        user_id=user_id,
        input_file_hash=input_hash,
        output_file_hash=output_hash,
        output_csv_b64=output_b64,
        output_filename=output_filename,
        validation=ValidationSummary(
            error_count=errors,
            warning_count=warnings,
            issue_rules=issue_rules,
            new_rows=new_rows,
            total_rows=total_rows,
        ),
        audit_chain=[a["integrity"]["record_hash"] for a in audits],
        run_hash=logged.run_hash,
    )


# ---------------------------------------------------------------------------
# Endpoint 1: Post New Lines (Workflow 1)
# ---------------------------------------------------------------------------


@router.post("/post-new-lines", response_model=WorkflowResponse)
def post_new_lines_endpoint(
    bmo_file: UploadFile = File(..., description="BMO daily CSV download"),
    existing_xlsx: UploadFile | None = File(
        default=None,
        description="Bank Rec CAD spreadsheet (optional — enables deduplication)",
    ),
    opening_balance: str = Form(
        default="0",
        description="Opening balance for running-balance recalculation",
    ),
    user_id: str = Depends(get_current_user),
    run_logger: RunLogger = Depends(get_run_logger),
) -> WorkflowResponse:
    """Identify new BMO rows, validate, produce a BC import CSV.

    Compares the uploaded BMO CSV against the existing Bank Rec CAD spreadsheet
    (if provided) to skip already-posted rows.  Returns the new rows as a
    validated, balance-verified CSV ready for Business Central import.
    """
    t0 = time.perf_counter()

    bmo_bytes = bmo_file.file.read()
    input_hash = _sha256(bmo_bytes)

    ob = _parse_decimal(opening_balance, "opening_balance")

    existing_df = None
    if existing_xlsx is not None:
        xlsx_bytes = existing_xlsx.file.read()
        if xlsx_bytes:
            try:
                existing_df = pd.read_excel(io.BytesIO(xlsx_bytes), dtype=str)
            except Exception as exc:
                raise HTTPException(
                    status_code=422,
                    detail=f"Cannot read existing XLSX: {exc}",
                )

    with tempfile.TemporaryDirectory() as tmpdir:
        out = Path(tmpdir) / "post_new_lines.csv"
        batch, validation, audits = post_new_lines(
            bmo_csv_content=bmo_bytes.decode("utf-8-sig"),
            existing_df=existing_df,
            opening_balance=ob,
            output_path=out,
        )
        output_b64, output_hash = _encode_output(out)

    duration_ms = int((time.perf_counter() - t0) * 1000)
    return _build_and_log(
        run_logger=run_logger,
        workflow=BankRecWorkflow.POST_NEW_LINES,
        user_id=user_id,
        input_file_name=bmo_file.filename,
        input_hash=input_hash,
        output_hash=output_hash,
        output_b64=output_b64,
        output_filename="post_new_lines.csv" if output_b64 else None,
        errors=validation.error_count,
        warnings=validation.warning_count,
        issue_rules=list({i.rule for i in validation.issues}),
        new_rows=batch.new_rows,
        total_rows=batch.total_rows,
        audits=audits,
        duration_ms=duration_ms,
    )


# ---------------------------------------------------------------------------
# Endpoint 2: Reconcile GL (Workflow 2)
# ---------------------------------------------------------------------------


@router.post("/reconcile-gl", response_model=WorkflowResponse)
def reconcile_gl_endpoint(
    bmo_file: UploadFile = File(..., description="BMO daily CSV download"),
    expected_ending_balance: str = Form(
        default="",
        description="Expected closing balance for verification (optional)",
    ),
    user_id: str = Depends(get_current_user),
    run_logger: RunLogger = Depends(get_run_logger),
) -> WorkflowResponse:
    """Strip reconciled rows and produce a BC Bank Acc. Reconciliation import CSV.

    Output columns (Transaction Date, Description, Amount) match the format
    expected by BC's Import Bank Statement button — ready for drag-and-drop.
    Amount is signed: deposits are positive, withdrawals are negative.
    """
    t0 = time.perf_counter()

    bmo_bytes = bmo_file.file.read()
    input_hash = _sha256(bmo_bytes)
    eeb = _parse_optional_decimal(expected_ending_balance)

    with tempfile.TemporaryDirectory() as tmpdir:
        out = Path(tmpdir) / "bank_rec_import.csv"
        batch, validation, audits = reconcile_gl(
            bmo_csv_content=bmo_bytes.decode("utf-8-sig"),
            expected_ending_balance=eeb,
            output_path=out,
        )
        output_b64, output_hash = _encode_output(out)

    duration_ms = int((time.perf_counter() - t0) * 1000)
    return _build_and_log(
        run_logger=run_logger,
        workflow=BankRecWorkflow.RECONCILE_GL,
        user_id=user_id,
        input_file_name=bmo_file.filename,
        input_hash=input_hash,
        output_hash=output_hash,
        output_b64=output_b64,
        output_filename="bank_rec_import.csv" if output_b64 else None,
        errors=validation.error_count,
        warnings=validation.warning_count,
        issue_rules=list({i.rule for i in validation.issues}),
        new_rows=batch.new_rows,
        total_rows=batch.total_rows,
        audits=audits,
        duration_ms=duration_ms,
    )


# ---------------------------------------------------------------------------
# Endpoint 3: Reconcile AMEX (Workflow 3)
# ---------------------------------------------------------------------------


@router.post("/reconcile-amex", response_model=WorkflowResponse)
def reconcile_amex_endpoint(
    bmo_file: UploadFile = File(..., description="BMO daily CSV download"),
    cutoff_date: str = Form(
        default="",
        description="Only include rows posted on or before this date (YYYY-MM-DD). "
                    "Defaults to the previous business day.",
    ),
    user_id: str = Depends(get_current_user),
    run_logger: RunLogger = Depends(get_run_logger),
) -> WorkflowResponse:
    """Filter to AMEX settlement rows, verify net balance is zero.

    Returns the filtered AMEX transactions.  Chain this with
    /cash-receipt-journal if you also need a BC Cash Receipt Journal import.
    """
    t0 = time.perf_counter()

    bmo_bytes = bmo_file.file.read()
    input_hash = _sha256(bmo_bytes)
    cd = _parse_optional_date(cutoff_date)

    batch, audits = reconcile_amex(
        bmo_csv_content=bmo_bytes.decode("utf-8-sig"),
        cutoff_date=cd,
    )

    duration_ms = int((time.perf_counter() - t0) * 1000)
    return _build_and_log(
        run_logger=run_logger,
        workflow=BankRecWorkflow.RECONCILE_AMEX,
        user_id=user_id,
        input_file_name=bmo_file.filename,
        input_hash=input_hash,
        output_hash=None,
        output_b64=None,
        output_filename=None,
        errors=0,
        warnings=0,
        issue_rules=[],
        new_rows=batch.new_rows,
        total_rows=batch.total_rows,
        audits=audits,
        duration_ms=duration_ms,
    )


# ---------------------------------------------------------------------------
# Endpoint 4: Cash Receipt Journal (Workflow 4)
# ---------------------------------------------------------------------------


@router.post("/cash-receipt-journal", response_model=WorkflowResponse)
def cash_receipt_journal_endpoint(
    bmo_file: UploadFile = File(..., description="BMO daily CSV download"),
    account_no: str = Form(
        ...,
        description="BC G/L account number for AMEX clearing (e.g. '11200')",
    ),
    account_type: str = Form(default="G/L Account"),
    document_type: str = Form(default="Payment"),
    cutoff_date: str = Form(
        default="",
        description="Only include AMEX rows on or before this date (YYYY-MM-DD)",
    ),
    user_id: str = Depends(get_current_user),
    run_logger: RunLogger = Depends(get_run_logger),
) -> WorkflowResponse:
    """Filter AMEX rows and produce a BC Cash Receipt Journal import CSV (CCAMEX batch).

    Internally chains Workflow 3 (reconcile_amex) then Workflow 4
    (export_cash_receipt_journal).  Every AMEX line in the uploaded BMO CSV up
    to the cutoff date becomes one journal line.  The output CSV has the exact
    seven columns BC's Cash Receipt Journal import expects.
    """
    t0 = time.perf_counter()

    bmo_bytes = bmo_file.file.read()
    input_hash = _sha256(bmo_bytes)
    cd = _parse_optional_date(cutoff_date)

    # Step 1 — filter to AMEX rows (Workflow 3)
    amex_batch, amex_audits = reconcile_amex(
        bmo_csv_content=bmo_bytes.decode("utf-8-sig"),
        cutoff_date=cd,
    )

    # Step 2 — format as BC Cash Receipt Journal (Workflow 4)
    with tempfile.TemporaryDirectory() as tmpdir:
        out = Path(tmpdir) / "ccamex.csv"
        lines, cj_audits = export_cash_receipt_journal(
            transactions=amex_batch.transactions,
            account_no=account_no,
            account_type=account_type,
            document_type=document_type,
            output_path=out,
        )
        output_b64, output_hash = _encode_output(out)

    all_audits = amex_audits + cj_audits
    duration_ms = int((time.perf_counter() - t0) * 1000)
    return _build_and_log(
        run_logger=run_logger,
        workflow=BankRecWorkflow.CASH_RECEIPT_JOURNAL,
        user_id=user_id,
        input_file_name=bmo_file.filename,
        input_hash=input_hash,
        output_hash=output_hash,
        output_b64=output_b64,
        output_filename="ccamex.csv" if output_b64 else None,
        errors=0,
        warnings=0,
        issue_rules=[],
        new_rows=len(lines),
        total_rows=amex_batch.total_rows,
        audits=all_audits,
        duration_ms=duration_ms,
    )


# ---------------------------------------------------------------------------
# Run history
# ---------------------------------------------------------------------------


@router.get("/runs", response_model=list[RunRecord])
def get_runs(
    run_logger: RunLogger = Depends(get_run_logger),
) -> list[RunRecord]:
    """Return the full run history from runs.jsonl in chronological order."""
    return run_logger.read_all()
