"""Workflow 4: BC Cash Receipt Journal export — CCAMEX batch.

Converts processed AMEX BankTransaction objects into the exact CSV format that
Business Central accepts for bulk import into the Cash Receipt Journal.

Every AMEX line becomes one journal line.  The human's only remaining job is to
open BC, paste the file, review the suggested matches, and click Post.

Output columns (must match BC Cash Receipt Journal import exactly):
  Posting Date | Document Type | Document No. | Account Type | Account No. | Description | Amount
"""

from __future__ import annotations

import csv
import uuid
from decimal import Decimal
from pathlib import Path

from sentient_ledger.agents.base import now_iso
from sentient_ledger.bank_rec.audit import create_batch_audit_record
from sentient_ledger.models.bank_reconciliation import (
    BankTransaction,
    CashReceiptJournalLine,
    ReconciliationBatch,
)
from sentient_ledger.models.enums import (
    AuditEventType,
    BankRecWorkflow,
    ReconciliationStatus,
    TransactionType,
)

# Exact BC column names — order matters for drag-and-drop import
_BC_COLUMNS: list[str] = [
    "Posting Date",
    "Document Type",
    "Document No.",
    "Account Type",
    "Account No.",
    "Description",
    "Amount",
]


def _make_doc_no(txn: BankTransaction, index: int) -> str:
    """Derive Document No. from bank_rec_number, falling back to CCAMEX + date + seq."""
    if txn.bank_rec_number:
        return str(txn.bank_rec_number)
    return f"CCAMEX{txn.posted_date.strftime('%Y%m%d')}{index + 1:03d}"


def _transaction_to_journal_line(
    txn: BankTransaction,
    index: int,
    account_type: str,
    account_no: str,
    document_type: str,
) -> CashReceiptJournalLine:
    """Map a BankTransaction to a single BC Cash Receipt Journal line.

    Amount sign convention:
      CREDIT (settlement received)  → positive  (money in)
      DEBIT  (chargeback/reversal)  → negative  (money out)
    """
    signed_amount = txn.amount if txn.transaction_type == TransactionType.CREDIT else -txn.amount

    return CashReceiptJournalLine(
        posting_date=txn.posted_date,
        document_type=document_type,
        document_no=_make_doc_no(txn, index),
        account_type=account_type,
        account_no=account_no,
        description=txn.description[:100],  # BC description field is 100 chars
        amount=signed_amount,
    )


def export_cash_receipt_journal(
    *,
    transactions: list[BankTransaction],
    account_no: str,
    account_type: str = "G/L Account",
    document_type: str = "Payment",
    batch_name: str = "CCAMEX",
    output_path=None,
    ingestion_id: str | None = None,
) -> tuple[list[CashReceiptJournalLine], list[dict]]:
    """Workflow 4: format transactions as a BC Cash Receipt Journal import CSV.

    Parameters
    ----------
    transactions:  AMEX BankTransaction objects (typically from reconcile_amex).
    account_no:    The BC G/L account number for AMEX clearing (e.g. "11200").
    account_type:  BC Account Type string; default "G/L Account".
    document_type: BC Document Type string; default "Payment".
    batch_name:    Journal batch name; default "CCAMEX" (informational only).
    output_path:   Where to write the CSV.  None = no file written.
    ingestion_id:  Propagated to the audit record.

    Returns
    -------
    (journal_lines, audit_records)
    """
    ingestion_id = ingestion_id or str(uuid.uuid4())
    batch_id = str(uuid.uuid4())
    audit_records: list[dict] = []

    journal_lines: list[CashReceiptJournalLine] = [
        _transaction_to_journal_line(txn, i, account_type, account_no, document_type)
        for i, txn in enumerate(transactions)
    ]

    if output_path is not None and journal_lines:
        _write_journal_csv(journal_lines, output_path)

    # Build a minimal batch for the audit record
    status = ReconciliationStatus.EXPORTED if journal_lines else ReconciliationStatus.PENDING
    batch = ReconciliationBatch(
        batch_id=batch_id,
        workflow=BankRecWorkflow.CASH_RECEIPT_JOURNAL,
        created_at=now_iso(),
        output_file=str(output_path) if output_path else None,
        total_rows=len(transactions),
        new_rows=len(journal_lines),
        status=status,
        transactions=transactions,
    )

    rec = create_batch_audit_record(
        batch,
        AuditEventType.COMMITTED,
        [],
        reasoning_snapshot=(
            f"Cash Receipt Journal export: {len(journal_lines)} lines, "
            f"batch={batch_name}, account_type={account_type}, account_no={account_no}"
        ),
    )
    audit_records.append(rec.model_dump())

    return journal_lines, audit_records


def _write_journal_csv(lines: list[CashReceiptJournalLine], output_path) -> None:
    """Write journal lines to a BC-compatible CSV (no BOM, MM/DD/YYYY dates)."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=_BC_COLUMNS)
        writer.writeheader()
        for line in lines:
            writer.writerow({
                "Posting Date": line.posting_date.strftime("%m/%d/%Y"),
                "Document Type": line.document_type,
                "Document No.": line.document_no,
                "Account Type": line.account_type,
                "Account No.": line.account_no,
                "Description": line.description,
                "Amount": line.amount,
            })
