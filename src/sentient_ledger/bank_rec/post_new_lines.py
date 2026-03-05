"""Workflow 1: Post New Lines.

Reads a BMO CSV download, identifies rows not already in the Bank Rec CAD Excel,
validates them, recalculates the running balance, and writes output for BC import.
"""

from __future__ import annotations

import csv
import hashlib
import json
import uuid
from datetime import date
from decimal import Decimal
from pathlib import Path

import pandas as pd

from sentient_ledger.agents.base import now_iso
from sentient_ledger.bank_rec.audit import (
    create_batch_audit_record,
    create_validation_audit_record,
)
from sentient_ledger.bank_rec.mappings import BMO_COLUMN_MAP
from sentient_ledger.bank_rec.parser import BankParseResult, parse_bmo_csv_file, parse_bmo_csv_string
from sentient_ledger.bank_rec.validator import classify_vendor, validate_bank_transactions
from sentient_ledger.models.bank_reconciliation import (
    BankRecValidationResult,
    BankTransaction,
    BankTransactionIntegrity,
    ReconciliationBatch,
)
from sentient_ledger.models.enums import (
    AuditEventType,
    BankRecWorkflow,
    ReconciliationStatus,
    TransactionType,
    VendorCategory,
)


def _row_hash(row: pd.Series) -> str:
    """SHA-256 of all raw string values in a DataFrame row."""
    data = {k: str(v) for k, v in row.items()}
    raw = json.dumps(data, sort_keys=True)
    return hashlib.sha256(raw.encode()).hexdigest()


def _parse_date(val: object) -> date | None:
    """Parse a date from various string formats; return None if unparseable."""
    if val is None or (isinstance(val, str) and val.strip() == ""):
        return None
    try:
        return pd.to_datetime(str(val), format="mixed").date()
    except Exception:  # noqa: BLE001
        return None


def _map_bmo_row_to_transaction(
    row: pd.Series,
    row_index: int,
    ingestion_id: str,
) -> BankTransaction:
    """Map a single BMO DataFrame row to a BankTransaction."""
    debit = row.get("Debit")
    credit = row.get("Credit")

    if credit is not None and credit != "" and (debit is None or debit == ""):
        txn_type = TransactionType.CREDIT
        amount = Decimal(str(credit))
    else:
        txn_type = TransactionType.DEBIT
        amount = Decimal(str(debit)) if (debit is not None and debit != "") else Decimal("0")

    description = str(row.get("Description", "")).strip()
    vendor_cat = classify_vendor(description)

    bank_rec_number = str(row.get("Bank Rec #", "")).strip() or None
    cc_date_raw = row.get("CC Merchant Rec Date")
    cc_date = _parse_date(cc_date_raw)

    balance_raw = row.get("Balance")
    balance = Decimal(str(balance_raw)) if balance_raw is not None else Decimal("0")

    integrity = BankTransactionIntegrity(
        source_row_hash=_row_hash(row),
        balance_verified=False,
    )

    return BankTransaction(
        record_id=str(uuid.uuid4()),
        ingestion_id=ingestion_id,
        ingested_at=now_iso(),
        posted_date=_parse_date(row.get("Posted")) or date.today(),
        value_date=_parse_date(row.get("Value Date")),
        description=description,
        transaction_type=txn_type,
        amount=amount,
        balance=balance,
        bank_rec_number=bank_rec_number,
        cc_merchant_rec_date=cc_date,
        vendor_category=VendorCategory(vendor_cat),
        is_reconciled=bank_rec_number is not None,
        integrity=integrity,
    )


def _normalize_amount(val: object) -> str:
    """Normalize a Debit/Credit cell to a canonical decimal string for key comparison.

    Handles None, 'nan', '', Decimal, float, and string variants.
    """
    from decimal import Decimal, InvalidOperation

    if val is None:
        return ""
    s = str(val).strip()
    if s in ("", "nan", "None", "NaN"):
        return ""
    try:
        return str(Decimal(s.replace(",", "")))
    except InvalidOperation:
        return s


def _normalize_date(val: object) -> str:
    """Normalize a date cell to YYYY-MM-DD string for key comparison."""
    if val is None:
        return ""
    s = str(val).strip()
    if s in ("", "nan", "None"):
        return ""
    try:
        return str(pd.to_datetime(s, format="mixed").date())
    except Exception:  # noqa: BLE001
        return s


def _identify_new_rows(
    bmo_df: pd.DataFrame,
    existing_df: pd.DataFrame,
) -> pd.DataFrame:
    """Return rows from bmo_df whose composite key is not in existing_df.

    Composite key: (posted_date_normalized, description, debit_normalized, credit_normalized).
    Normalization handles the Excel vs CSV representation differences.
    """

    def _key(row: pd.Series) -> tuple:
        return (
            _normalize_date(row.get("Posted")),
            str(row.get("Description", "")).strip(),
            _normalize_amount(row.get("Debit")),
            _normalize_amount(row.get("Credit")),
        )

    existing_keys: set[tuple] = set()
    for _, row in existing_df.iterrows():
        existing_keys.add(_key(row))

    mask = bmo_df.apply(lambda r: _key(r) not in existing_keys, axis=1)
    return bmo_df[mask].reset_index(drop=True)


def _auto_populate_cc_merchant_date(
    txns: list[BankTransaction],
) -> list[BankTransaction]:
    """Set cc_merchant_rec_date to posted_date for ELAVON/AMEX rows that lack it."""
    from sentient_ledger.bank_rec.mappings import CC_MERCHANT_REC_CATEGORIES

    updated: list[BankTransaction] = []
    for txn in txns:
        if (
            txn.vendor_category.value in CC_MERCHANT_REC_CATEGORIES
            and txn.cc_merchant_rec_date is None
        ):
            updated.append(txn.model_copy(update={"cc_merchant_rec_date": txn.posted_date}))
        else:
            updated.append(txn)
    return updated


def _recalculate_running_balance(
    txns: list[BankTransaction],
    opening_balance: Decimal,
) -> list[BankTransaction]:
    """Recalculate balance for each transaction from opening_balance forward."""
    result: list[BankTransaction] = []
    running = opening_balance
    for txn in txns:
        if txn.transaction_type == TransactionType.CREDIT:
            running = running + txn.amount
        else:
            running = running - txn.amount
        updated = txn.model_copy(
            update={
                "balance": running,
                "integrity": txn.integrity.model_copy(update={"balance_verified": True}),
            }
        )
        result.append(updated)
    return result


def _load_existing_df(existing_xlsx_path: str | Path | None, existing_df: pd.DataFrame | None) -> pd.DataFrame:
    """Return a DataFrame of existing bank rec rows from either an xlsx path or a provided df."""
    if existing_df is not None:
        return existing_df
    if existing_xlsx_path is not None:
        try:
            return pd.read_excel(existing_xlsx_path, dtype=str)
        except Exception:  # noqa: BLE001
            return pd.DataFrame()
    return pd.DataFrame()


def _parse_input(
    bmo_csv_path: str | Path | None,
    bmo_csv_content: str | None,
) -> BankParseResult:
    if bmo_csv_content is not None:
        return parse_bmo_csv_string(bmo_csv_content)
    if bmo_csv_path is not None:
        return parse_bmo_csv_file(bmo_csv_path)
    result = BankParseResult()
    result.parse_errors.append("No BMO CSV input provided (path or content required)")
    return result


def post_new_lines(
    *,
    bmo_csv_path: str | Path | None = None,
    bmo_csv_content: str | None = None,
    existing_xlsx_path: str | Path | None = None,
    existing_df: pd.DataFrame | None = None,
    opening_balance: Decimal = Decimal("0"),
    output_path: str | Path | None = None,
    ingestion_id: str | None = None,
) -> tuple[ReconciliationBatch, BankRecValidationResult, list[dict]]:
    """Workflow 1: identify new BMO rows, validate, write output for BC import.

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
            workflow=BankRecWorkflow.POST_NEW_LINES,
            created_at=now_iso(),
            source_file=str(bmo_csv_path) if bmo_csv_path else None,
            status=ReconciliationStatus.PENDING,
        )
        return empty_batch, BankRecValidationResult(), audit_records

    bmo_df = parse_result.df

    # --- 2. Load existing Bank Rec CAD ---
    ext_df = _load_existing_df(existing_xlsx_path, existing_df)

    # --- 3. Identify new rows ---
    new_df = _identify_new_rows(bmo_df, ext_df)
    new_count = len(new_df)
    skipped = len(bmo_df) - new_count

    if new_count == 0:
        empty_batch = ReconciliationBatch(
            batch_id=batch_id,
            workflow=BankRecWorkflow.POST_NEW_LINES,
            created_at=now_iso(),
            source_file=str(bmo_csv_path) if bmo_csv_path else None,
            total_rows=len(bmo_df),
            new_rows=0,
            skipped_rows=skipped,
            opening_balance=opening_balance,
            status=ReconciliationStatus.STAGED,
        )
        return empty_batch, BankRecValidationResult(), audit_records

    # --- 4. Map rows to BankTransaction ---
    txns: list[BankTransaction] = [
        _map_bmo_row_to_transaction(row, i, ingestion_id)
        for i, (_, row) in enumerate(new_df.iterrows())
    ]

    # --- 5. Auto-populate CC Merchant Rec Date ---
    txns = _auto_populate_cc_merchant_date(txns)

    # --- 6. Recalculate running balance ---
    txns = _recalculate_running_balance(txns, opening_balance)

    closing_balance = txns[-1].balance if txns else opening_balance

    # --- 7. Validate ---
    validation_result = validate_bank_transactions(txns)

    # --- 8. Build batch ---
    status = ReconciliationStatus.STAGED if validation_result.error_count == 0 else ReconciliationStatus.PENDING
    batch = ReconciliationBatch(
        batch_id=batch_id,
        workflow=BankRecWorkflow.POST_NEW_LINES,
        created_at=now_iso(),
        source_file=str(bmo_csv_path) if bmo_csv_path else None,
        output_file=str(output_path) if output_path else None,
        total_rows=len(bmo_df),
        new_rows=new_count,
        reconciled_rows=sum(1 for t in txns if t.is_reconciled),
        skipped_rows=skipped,
        opening_balance=opening_balance,
        closing_balance=closing_balance,
        balance_verified=True,
        status=status,
        transactions=txns,
    )

    # --- 9. Write output CSV ---
    if output_path is not None and txns:
        _write_output_csv(txns, output_path)

    # --- 10. Generate audit records ---
    rec1 = create_batch_audit_record(
        batch,
        AuditEventType.CREATED,
        [],
        reasoning_snapshot=f"Post new lines: {new_count} new rows from {parse_result.total_rows} total",
    )
    audit_records.append(rec1.model_dump())

    rec2 = create_validation_audit_record(batch_id, validation_result, audit_records)
    audit_records.append(rec2.model_dump())

    return batch, validation_result, audit_records


def _write_output_csv(txns: list[BankTransaction], output_path: str | Path) -> None:
    """Write transactions to a CSV file for BC import."""
    fieldnames = [
        "record_id", "posted_date", "value_date", "description",
        "transaction_type", "amount", "balance", "bank_rec_number",
        "cc_merchant_rec_date", "vendor_category", "is_reconciled",
    ]
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for txn in txns:
            writer.writerow({
                "record_id": txn.record_id,
                "posted_date": txn.posted_date,
                "value_date": txn.value_date,
                "description": txn.description,
                "transaction_type": txn.transaction_type.value,
                "amount": txn.amount,
                "balance": txn.balance,
                "bank_rec_number": txn.bank_rec_number or "",
                "cc_merchant_rec_date": txn.cc_merchant_rec_date or "",
                "vendor_category": txn.vendor_category.value,
                "is_reconciled": txn.is_reconciled,
            })
