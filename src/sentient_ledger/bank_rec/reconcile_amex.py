"""Workflow 3: Reconcile AMEX/VM settlements.

Filters BMO CSV to AMEX_SETTLEMENT rows posted on or before the previous business
day, verifies net balance is zero, and writes output for BC import.
"""

from __future__ import annotations

import csv
import uuid
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from sentient_ledger.agents.base import now_iso
from sentient_ledger.bank_rec.audit import create_batch_audit_record
from sentient_ledger.bank_rec.mappings import CC_MERCHANT_REC_CATEGORIES
from sentient_ledger.bank_rec.parser import BankParseResult, parse_bmo_csv_file, parse_bmo_csv_string
from sentient_ledger.bank_rec.post_new_lines import _map_bmo_row_to_transaction
from sentient_ledger.models.bank_reconciliation import (
    BankTransaction,
    ReconciliationBatch,
)
from sentient_ledger.models.enums import (
    AuditEventType,
    BankRecWorkflow,
    ReconciliationStatus,
    TransactionType,
    VendorCategory,
)


def _previous_business_day(ref: date) -> date:
    """Return the business day (Mon–Fri) immediately before ref."""
    prev = ref - timedelta(days=1)
    while prev.weekday() >= 5:  # 5=Saturday, 6=Sunday
        prev -= timedelta(days=1)
    return prev


def _filter_amex_rows(
    txns: list[BankTransaction],
) -> list[BankTransaction]:
    """Keep only rows classified as AMEX_SETTLEMENT."""
    return [t for t in txns if t.vendor_category == VendorCategory.AMEX_SETTLEMENT]


def _filter_up_to_date(
    txns: list[BankTransaction],
    cutoff: date,
) -> list[BankTransaction]:
    """Keep only rows with posted_date <= cutoff."""
    return [t for t in txns if t.posted_date <= cutoff]


def _compute_net_balance(txns: list[BankTransaction]) -> Decimal:
    """Compute sum(credits) - sum(debits) across all transactions."""
    net = Decimal("0")
    for txn in txns:
        if txn.transaction_type == TransactionType.CREDIT:
            net += txn.amount
        else:
            net -= txn.amount
    return net


def _parse_input(path, content) -> BankParseResult:
    if content is not None:
        return parse_bmo_csv_string(content)
    if path is not None:
        return parse_bmo_csv_file(path)
    result = BankParseResult()
    result.parse_errors.append("No BMO CSV input provided (path or content required)")
    return result


def reconcile_amex(
    *,
    bmo_csv_path=None,
    bmo_csv_content: str | None = None,
    cutoff_date: date | None = None,
    output_path=None,
    ingestion_id: str | None = None,
) -> tuple[ReconciliationBatch, list[dict]]:
    """Workflow 3: filter AMEX rows, verify net zero, write output.

    Returns (batch, audit_records).
    """
    ingestion_id = ingestion_id or str(uuid.uuid4())
    batch_id = str(uuid.uuid4())
    audit_records: list[dict] = []

    # Default cutoff: previous business day from today
    if cutoff_date is None:
        cutoff_date = _previous_business_day(date.today())

    # --- 1. Parse BMO CSV ---
    parse_result = _parse_input(bmo_csv_path, bmo_csv_content)
    if parse_result.parse_errors or parse_result.df is None:
        empty_batch = ReconciliationBatch(
            batch_id=batch_id,
            workflow=BankRecWorkflow.RECONCILE_AMEX,
            created_at=now_iso(),
            source_file=str(bmo_csv_path) if bmo_csv_path else None,
            status=ReconciliationStatus.PENDING,
        )
        return empty_batch, audit_records

    bmo_df = parse_result.df
    total_rows = len(bmo_df)

    # --- 2. Map all rows to BankTransaction ---
    all_txns: list[BankTransaction] = [
        _map_bmo_row_to_transaction(row, i, ingestion_id)
        for i, (_, row) in enumerate(bmo_df.iterrows())
    ]

    # --- 3. Filter AMEX rows ---
    amex_txns = _filter_amex_rows(all_txns)

    # --- 4. Filter up to cutoff date ---
    amex_txns = _filter_up_to_date(amex_txns, cutoff_date)

    # --- 5. Compute net balance ---
    net = _compute_net_balance(amex_txns)
    is_net_zero = net == Decimal("0")

    status = ReconciliationStatus.RECONCILED if is_net_zero else ReconciliationStatus.STAGED

    closing_balance = amex_txns[-1].balance if amex_txns else Decimal("0")
    opening_balance = Decimal("0")

    batch = ReconciliationBatch(
        batch_id=batch_id,
        workflow=BankRecWorkflow.RECONCILE_AMEX,
        created_at=now_iso(),
        source_file=str(bmo_csv_path) if bmo_csv_path else None,
        output_file=str(output_path) if output_path else None,
        total_rows=total_rows,
        new_rows=len(amex_txns),
        reconciled_rows=len(amex_txns),
        skipped_rows=total_rows - len(amex_txns),
        opening_balance=opening_balance,
        closing_balance=closing_balance,
        balance_verified=is_net_zero,
        status=status,
        transactions=amex_txns,
    )

    # --- 6. Write output CSV ---
    if output_path is not None and amex_txns:
        _write_output_csv(amex_txns, output_path)

    # --- 7. Generate audit record ---
    rec = create_batch_audit_record(
        batch,
        AuditEventType.CREATED,
        [],
        reasoning_snapshot=(
            f"Reconcile AMEX: {len(amex_txns)} AMEX rows up to {cutoff_date}, "
            f"net={net}, is_net_zero={is_net_zero}"
        ),
    )
    audit_records.append(rec.model_dump())

    return batch, audit_records


def _write_output_csv(txns: list[BankTransaction], output_path) -> None:
    """Write AMEX transactions to a CSV for BC import."""
    fieldnames = [
        "posted_date", "description", "transaction_type", "amount",
        "cc_merchant_rec_date", "vendor_category",
    ]
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for txn in txns:
            writer.writerow({
                "posted_date": txn.posted_date,
                "description": txn.description,
                "transaction_type": txn.transaction_type.value,
                "amount": txn.amount,
                "cc_merchant_rec_date": txn.cc_merchant_rec_date or "",
                "vendor_category": txn.vendor_category.value,
            })
