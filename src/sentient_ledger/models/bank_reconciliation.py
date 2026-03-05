"""Pydantic v2 models for the BMO bank reconciliation module."""

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from sentient_ledger.models.enums import (
    BankRecWorkflow,
    ReconciliationStatus,
    TransactionType,
    VendorCategory,
)


class BankTransactionIntegrity(BaseModel):
    source_row_hash: str
    balance_verified: bool = False


class BankTransaction(BaseModel):
    record_id: str
    source: str = "BMO"
    ingestion_id: str
    ingested_at: str

    posted_date: date
    value_date: date | None = None
    description: str
    transaction_type: TransactionType
    amount: Decimal
    balance: Decimal

    bank_rec_number: str | None = None
    cc_merchant_rec_date: date | None = None
    vendor_category: VendorCategory = VendorCategory.UNKNOWN
    is_reconciled: bool = False

    integrity: BankTransactionIntegrity


class ServiceChargePair(BaseModel):
    fee_row_index: int
    rebate_row_index: int
    fee_amount: Decimal
    rebate_amount: Decimal
    net_amount: Decimal
    is_net_zero: bool


class ReconciliationBatch(BaseModel):
    batch_id: str
    workflow: BankRecWorkflow
    created_at: str
    source_file: str | None = None
    output_file: str | None = None

    total_rows: int = 0
    new_rows: int = 0
    reconciled_rows: int = 0
    skipped_rows: int = 0

    opening_balance: Decimal = Decimal("0")
    closing_balance: Decimal = Decimal("0")
    balance_verified: bool = False

    status: ReconciliationStatus = ReconciliationStatus.PENDING
    transactions: list[BankTransaction] = Field(default_factory=list)
    service_charge_pairs: list[ServiceChargePair] = Field(default_factory=list)


class BankRecValidationIssue(BaseModel):
    rule: str
    severity: str  # "ERROR" | "WARNING"
    message: str
    row_index: int | None = None
    column: str | None = None


class BankRecValidationResult(BaseModel):
    valid_transactions: list[BankTransaction] = Field(default_factory=list)
    issues: list[BankRecValidationIssue] = Field(default_factory=list)
    error_count: int = 0
    warning_count: int = 0
