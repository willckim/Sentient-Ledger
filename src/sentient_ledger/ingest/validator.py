"""Validation rules for mapped canonical records."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal

from sentient_ledger.ingest.mappings import SUPPORTED_CURRENCIES


@dataclass
class ValidationIssue:
    """A single validation problem."""

    rule: str
    severity: str  # "ERROR" or "WARNING"
    message: str
    row_index: int


@dataclass
class ValidationResult:
    """Aggregated validation output."""

    valid_records: list[dict] = field(default_factory=list)
    issues: list[ValidationIssue] = field(default_factory=list)
    error_count: int = 0
    warning_count: int = 0


# ---------------------------------------------------------------------------
# Trial Balance validation
# ---------------------------------------------------------------------------

def validate_trial_balance_records(records: list[dict]) -> ValidationResult:
    """Validate a list of mapped TB records. ERROR → exclude; WARNING → pass."""
    result = ValidationResult()

    for i, rec in enumerate(records):
        row_errors: list[ValidationIssue] = []
        balances = rec.get("balances", {})
        currency = rec.get("currency", {})
        account = rec.get("account", {})

        # debits_non_negative
        if balances.get("debits", Decimal("0")) < 0:
            issue = ValidationIssue(
                rule="debits_non_negative",
                severity="ERROR",
                message=f"Debits is negative: {balances['debits']}",
                row_index=i,
            )
            row_errors.append(issue)
            result.issues.append(issue)
            result.error_count += 1

        # credits_non_negative
        if balances.get("credits", Decimal("0")) < 0:
            issue = ValidationIssue(
                rule="credits_non_negative",
                severity="ERROR",
                message=f"Credits is negative: {balances['credits']}",
                row_index=i,
            )
            row_errors.append(issue)
            result.issues.append(issue)
            result.error_count += 1

        # account_code_min_length (WARNING)
        code = account.get("code", "")
        if len(code) < 4:
            issue = ValidationIssue(
                rule="account_code_min_length",
                severity="WARNING",
                message=f"Account code '{code}' is shorter than 4 characters",
                row_index=i,
            )
            result.issues.append(issue)
            result.warning_count += 1

        # currency_supported
        txn_currency = currency.get("transaction", "USD")
        if txn_currency not in SUPPORTED_CURRENCIES:
            issue = ValidationIssue(
                rule="currency_supported",
                severity="ERROR",
                message=f"Unsupported currency: {txn_currency}",
                row_index=i,
            )
            row_errors.append(issue)
            result.issues.append(issue)
            result.error_count += 1

        # Only include record if no ERRORs
        if not row_errors:
            result.valid_records.append(rec)

    return result


# ---------------------------------------------------------------------------
# Fixed Asset validation
# ---------------------------------------------------------------------------

_PERIOD_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def validate_fixed_asset_records(records: list[dict]) -> ValidationResult:
    """Validate a list of mapped FA records. ERROR → exclude; WARNING → pass."""
    result = ValidationResult()

    for i, rec in enumerate(records):
        row_errors: list[ValidationIssue] = []
        acq = rec.get("acquisition", {})
        state = rec.get("current_state", {})

        cost = acq.get("cost", Decimal("0"))
        salvage = acq.get("salvage_value", Decimal("0"))
        useful_life = acq.get("useful_life_months", 0)
        nbv = state.get("net_book_value", Decimal("0"))

        # cost_positive
        if cost <= 0:
            issue = ValidationIssue(
                rule="cost_positive",
                severity="ERROR",
                message=f"Acquisition cost must be positive: {cost}",
                row_index=i,
            )
            row_errors.append(issue)
            result.issues.append(issue)
            result.error_count += 1

        # salvage_non_negative
        if salvage < 0:
            issue = ValidationIssue(
                rule="salvage_non_negative",
                severity="ERROR",
                message=f"Salvage value is negative: {salvage}",
                row_index=i,
            )
            row_errors.append(issue)
            result.issues.append(issue)
            result.error_count += 1

        # salvage_less_than_cost
        if salvage >= cost and cost > 0:
            issue = ValidationIssue(
                rule="salvage_less_than_cost",
                severity="ERROR",
                message=f"Salvage value ({salvage}) must be less than cost ({cost})",
                row_index=i,
            )
            row_errors.append(issue)
            result.issues.append(issue)
            result.error_count += 1

        # useful_life_positive
        if useful_life <= 0:
            issue = ValidationIssue(
                rule="useful_life_positive",
                severity="ERROR",
                message=f"Useful life must be positive: {useful_life}",
                row_index=i,
            )
            row_errors.append(issue)
            result.issues.append(issue)
            result.error_count += 1

        # nbv_non_negative (WARNING)
        if nbv < 0:
            issue = ValidationIssue(
                rule="nbv_non_negative",
                severity="WARNING",
                message=f"Net book value is negative: {nbv}",
                row_index=i,
            )
            result.issues.append(issue)
            result.warning_count += 1

        # Only include record if no ERRORs
        if not row_errors:
            result.valid_records.append(rec)

    return result


# ---------------------------------------------------------------------------
# Depreciation Schedule validation
# ---------------------------------------------------------------------------

def validate_depreciation_entries(records: list[dict]) -> ValidationResult:
    """Validate a list of mapped depreciation entry dicts. ERROR → exclude; WARNING → pass."""
    result = ValidationResult()

    for i, rec in enumerate(records):
        row_errors: list[ValidationIssue] = []
        amount = rec.get("amount", Decimal("0"))
        accumulated = rec.get("accumulated", Decimal("0"))
        nbv = rec.get("net_book_value", Decimal("0"))
        period = rec.get("period", "")

        # amount_non_negative
        if amount < 0:
            issue = ValidationIssue(
                rule="amount_non_negative",
                severity="ERROR",
                message=f"Depreciation amount is negative: {amount}",
                row_index=i,
            )
            row_errors.append(issue)
            result.issues.append(issue)
            result.error_count += 1

        # accumulated_non_negative
        if accumulated < 0:
            issue = ValidationIssue(
                rule="accumulated_non_negative",
                severity="ERROR",
                message=f"Accumulated depreciation is negative: {accumulated}",
                row_index=i,
            )
            row_errors.append(issue)
            result.issues.append(issue)
            result.error_count += 1

        # nbv_non_negative (WARNING)
        if nbv < 0:
            issue = ValidationIssue(
                rule="nbv_non_negative",
                severity="WARNING",
                message=f"Net book value is negative: {nbv}",
                row_index=i,
            )
            result.issues.append(issue)
            result.warning_count += 1

        # period_format_valid
        if not _PERIOD_RE.match(period):
            issue = ValidationIssue(
                rule="period_format_valid",
                severity="ERROR",
                message=f"Invalid period format: '{period}'",
                row_index=i,
            )
            row_errors.append(issue)
            result.issues.append(issue)
            result.error_count += 1

        if not row_errors:
            result.valid_records.append(rec)

    return result
