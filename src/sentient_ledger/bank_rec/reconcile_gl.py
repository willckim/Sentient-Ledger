"""Workflow 2: Reconcile GL Account 11105.

Reads a BMO CSV download, removes already-reconciled rows (Bank Rec # populated),
validates the remainder, verifies the ending balance, and writes a clean CSV for
BC Bank Account Reconciliation import.
"""

from __future__ import annotations

import csv
import uuid
from decimal import Decimal
from pathlib import Path

from sentient_ledger.agents.base import now_iso
from sentient_ledger.bank_rec.audit import create_batch_audit_record
from sentient_ledger.bank_rec.parser import BankParseResult, parse_bmo_csv_file, parse_bmo_csv_string
from sentient_ledger.bank_rec.post_new_lines import _map_bmo_row_to_transaction
from sentient_ledger.bank_rec.validator import validate_bank_transactions
from sentient_ledger.models.bank_reconciliation import (
    BankRecValidationResult,
    BankTransaction,
    ReconciliationBatch,
)
from sentient_ledger.models.enums import (
    AuditEventType,
    BankRecWorkflow,
    ReconciliationStatus,
)


def _remove_reconciled_rows(df) -> tuple:
    """Split DataFrame into reconciled and unreconciled rows.

    Returns (unreconciled_df, reconciled_count).
    """
    import pandas as pd

    has_rec = df["Bank Rec #"].notna() if "Bank Rec #" in df.columns else pd.Series([False] * len(df))
    # Also treat empty strings as unreconciled
    has_rec = has_rec & (df.get("Bank Rec #", pd.Series([""] * len(df))).str.strip() != "")
    reconciled_count = int(has_rec.sum())
    unreconciled_df = df[~has_rec].reset_index(drop=True)
    return unreconciled_df, reconciled_count


def _verify_ending_balance(
    txns: list[BankTransaction],
    expected_ending_balance: Decimal | None,
) -> bool:
    """Return True if the last transaction's balance matches the expected ending balance."""
    if not txns or expected_ending_balance is None:
        return True
    TOLERANCE = Decimal("0.01")
    return abs(txns[-1].balance - expected_ending_balance) <= TOLERANCE


def _parse_input(path, content) -> BankParseResult:
    if content is not None:
        return parse_bmo_csv_string(content)
    if path is not None:
        return parse_bmo_csv_file(path)
    result = BankParseResult()
    result.parse_errors.append("No BMO CSV input provided (path or content required)")
    return result


def reconcile_gl(
    *,
    bmo_csv_path=None,
    bmo_csv_content: str | None = None,
    expected_ending_balance: Decimal | None = None,
    output_path=None,
    ingestion_id: str | None = None,
) -> tuple[ReconciliationBatch, BankRecValidationResult, list[dict]]:
    """Workflow 2: strip reconciled rows, validate remainder, write for BC import.

    Returns (batch, validation_result, audit_records).
    """
    ingestion_id = ingestion_id or str(uuid.uuid4())
    batch_id = str(uuid.uuid4())
    audit_records: list[dict] = []

    # --- 1. Parse BMO CSV ---
    parse_result = _parse_input(bmo_csv_path, bmo_csv_content)
    if parse_result.parse_errors or parse_result.df is None:
        empty_batch = ReconciliationBatch(
            batch_id=batch_id,
            workflow=BankRecWorkflow.RECONCILE_GL,
            created_at=now_iso(),
            source_file=str(bmo_csv_path) if bmo_csv_path else None,
            status=ReconciliationStatus.PENDING,
        )
        return empty_batch, BankRecValidationResult(), audit_records

    bmo_df = parse_result.df
    total_rows = len(bmo_df)

    # --- 2. Remove already-reconciled rows ---
    unreconciled_df, reconciled_count = _remove_reconciled_rows(bmo_df)

    # --- 3. Map to BankTransaction ---
    txns: list[BankTransaction] = [
        _map_bmo_row_to_transaction(row, i, ingestion_id)
        for i, (_, row) in enumerate(unreconciled_df.iterrows())
    ]

    # --- 4. Validate ---
    validation_result = validate_bank_transactions(txns)

    # --- 5. Verify ending balance ---
    balance_ok = _verify_ending_balance(txns, expected_ending_balance)

    closing_balance = txns[-1].balance if txns else Decimal("0")
    opening_balance = txns[0].balance - (
        txns[0].amount if txns[0].transaction_type.value == "CREDIT"
        else -txns[0].amount
    ) if txns else Decimal("0")

    status = (
        ReconciliationStatus.RECONCILED
        if validation_result.error_count == 0 and balance_ok
        else ReconciliationStatus.PENDING
    )

    batch = ReconciliationBatch(
        batch_id=batch_id,
        workflow=BankRecWorkflow.RECONCILE_GL,
        created_at=now_iso(),
        source_file=str(bmo_csv_path) if bmo_csv_path else None,
        output_file=str(output_path) if output_path else None,
        total_rows=total_rows,
        new_rows=len(txns),
        reconciled_rows=reconciled_count,
        skipped_rows=0,
        opening_balance=opening_balance,
        closing_balance=closing_balance,
        balance_verified=balance_ok,
        status=status,
        transactions=txns,
    )

    # --- 6. Write output CSV ---
    if output_path is not None and txns:
        _write_output_csv(txns, output_path)

    # --- 7. Generate audit record ---
    rec = create_batch_audit_record(
        batch,
        AuditEventType.CREATED,
        [],
        reasoning_snapshot=(
            f"Reconcile GL: {reconciled_count} reconciled rows removed, "
            f"{len(txns)} unreconciled rows remain, balance_ok={balance_ok}"
        ),
    )
    audit_records.append(rec.model_dump())

    return batch, validation_result, audit_records


def _write_output_csv(txns: list[BankTransaction], output_path) -> None:
    """Write unreconciled transactions to a CSV for BC import."""
    fieldnames = [
        "posted_date", "value_date", "description",
        "transaction_type", "amount", "balance",
    ]
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for txn in txns:
            writer.writerow({
                "posted_date": txn.posted_date,
                "value_date": txn.value_date,
                "description": txn.description,
                "transaction_type": txn.transaction_type.value,
                "amount": txn.amount,
                "balance": txn.balance,
            })
