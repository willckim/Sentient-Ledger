"""Validation rules for BMO bank transactions."""

from __future__ import annotations

from decimal import Decimal

from sentient_ledger.bank_rec.mappings import (
    CC_MERCHANT_REC_CATEGORIES,
    SERVICE_CHARGE_FEE_PATTERN,
    SERVICE_CHARGE_REBATE_PATTERN,
    VENDOR_PATTERNS,
)
from sentient_ledger.models.bank_reconciliation import (
    BankRecValidationIssue,
    BankRecValidationResult,
    BankTransaction,
    ServiceChargePair,
)
from sentient_ledger.models.enums import TransactionType, VendorCategory


def classify_vendor(description: str) -> str:
    """Return the first matching VendorCategory value for the given description.

    Iterates VENDOR_PATTERNS in order (specific before generic). Falls back to
    VendorCategory.UNKNOWN if no pattern matches.
    """
    upper = description.upper()
    for substring, category in VENDOR_PATTERNS:
        if substring.upper() in upper:
            return category.value
    return VendorCategory.UNKNOWN.value


def validate_debit_credit_exclusive(
    txns: list[BankTransaction],
) -> list[BankRecValidationIssue]:
    """Flag rows where both Debit and Credit were non-empty (caught at map time)."""
    # This rule is enforced during mapping; we surface it here as a no-op pass-through
    # since transactions with both populated are excluded before reaching validation.
    # The mapper stores them in a separate list and those are reported separately.
    return []


def validate_running_balance(
    txns: list[BankTransaction],
) -> list[BankRecValidationIssue]:
    """Verify each row's balance equals the previous balance ± the transaction amount."""
    issues: list[BankRecValidationIssue] = []
    if len(txns) < 2:
        return issues

    TOLERANCE = Decimal("0.01")

    for i in range(1, len(txns)):
        prev = txns[i - 1]
        curr = txns[i]
        if curr.transaction_type == TransactionType.CREDIT:
            expected = prev.balance + curr.amount
        else:
            expected = prev.balance - curr.amount

        if abs(expected - curr.balance) > TOLERANCE:
            issues.append(
                BankRecValidationIssue(
                    rule="RUNNING_BALANCE",
                    severity="ERROR",
                    message=(
                        f"Row {i}: balance {curr.balance} does not match expected "
                        f"{expected} (prev={prev.balance}, amount={curr.amount}, "
                        f"type={curr.transaction_type.value})"
                    ),
                    row_index=i,
                    column="Balance",
                )
            )
    return issues


def validate_no_duplicates(
    txns: list[BankTransaction],
) -> list[BankRecValidationIssue]:
    """Flag duplicate rows sharing (posted_date, description, amount, type)."""
    issues: list[BankRecValidationIssue] = []
    seen: dict[tuple, int] = {}
    for i, txn in enumerate(txns):
        key = (str(txn.posted_date), txn.description, txn.amount, txn.transaction_type)
        if key in seen:
            issues.append(
                BankRecValidationIssue(
                    rule="NO_DUPLICATES",
                    severity="ERROR",
                    message=(
                        f"Row {i} is a duplicate of row {seen[key]}: "
                        f"({txn.posted_date}, {txn.description[:30]}, {txn.amount})"
                    ),
                    row_index=i,
                )
            )
        else:
            seen[key] = i
    return issues


def validate_service_charge_pairs(
    txns: list[BankTransaction],
) -> tuple[list[BankRecValidationIssue], list[ServiceChargePair]]:
    """Match PLAN FEE debits to FULL PLAN FEE REBATE credits by amount."""
    issues: list[BankRecValidationIssue] = []
    pairs: list[ServiceChargePair] = []

    fees: list[tuple[int, BankTransaction]] = []
    rebates: list[tuple[int, BankTransaction]] = []

    for i, txn in enumerate(txns):
        desc_upper = txn.description.upper()
        if SERVICE_CHARGE_REBATE_PATTERN.upper() in desc_upper:
            rebates.append((i, txn))
        elif SERVICE_CHARGE_FEE_PATTERN.upper() in desc_upper:
            fees.append((i, txn))

    # Match fee→rebate by amount
    unmatched_rebates = list(rebates)
    for fee_idx, fee_txn in fees:
        matched = None
        for r_i, (rebate_idx, rebate_txn) in enumerate(unmatched_rebates):
            if rebate_txn.amount == fee_txn.amount:
                matched = (r_i, rebate_idx, rebate_txn)
                break
        if matched is not None:
            r_i, rebate_idx, rebate_txn = matched
            net = fee_txn.amount - rebate_txn.amount
            pairs.append(
                ServiceChargePair(
                    fee_row_index=fee_idx,
                    rebate_row_index=rebate_idx,
                    fee_amount=fee_txn.amount,
                    rebate_amount=rebate_txn.amount,
                    net_amount=net,
                    is_net_zero=(net == Decimal("0")),
                )
            )
            unmatched_rebates.pop(r_i)
        else:
            issues.append(
                BankRecValidationIssue(
                    rule="SERVICE_CHARGE_PAIRS",
                    severity="WARNING",
                    message=(
                        f"Row {fee_idx}: PLAN FEE of {fee_txn.amount} has no "
                        "matching FULL PLAN FEE REBATE"
                    ),
                    row_index=fee_idx,
                )
            )

    for rebate_idx, rebate_txn in unmatched_rebates:
        issues.append(
            BankRecValidationIssue(
                rule="SERVICE_CHARGE_PAIRS",
                severity="WARNING",
                message=(
                    f"Row {rebate_idx}: FULL PLAN FEE REBATE of {rebate_txn.amount} "
                    "has no matching PLAN FEE"
                ),
                row_index=rebate_idx,
            )
        )

    return issues, pairs


def validate_cc_merchant_rec_dates(
    txns: list[BankTransaction],
) -> list[BankRecValidationIssue]:
    """Warn when an ELAVON/AMEX transaction has no CC Merchant Rec Date."""
    issues: list[BankRecValidationIssue] = []
    for i, txn in enumerate(txns):
        if (
            txn.vendor_category.value in CC_MERCHANT_REC_CATEGORIES
            and txn.cc_merchant_rec_date is None
        ):
            issues.append(
                BankRecValidationIssue(
                    rule="CC_MERCHANT_REC_DATE",
                    severity="WARNING",
                    message=(
                        f"Row {i}: {txn.vendor_category.value} transaction "
                        f"'{txn.description[:40]}' has no CC Merchant Rec Date"
                    ),
                    row_index=i,
                    column="CC Merchant Rec Date",
                )
            )
    return issues


def validate_bank_transactions(
    txns: list[BankTransaction],
) -> BankRecValidationResult:
    """Run all 5 validation rules and return a consolidated result."""
    all_issues: list[BankRecValidationIssue] = []

    all_issues.extend(validate_debit_credit_exclusive(txns))
    all_issues.extend(validate_running_balance(txns))
    all_issues.extend(validate_no_duplicates(txns))
    sc_issues, _ = validate_service_charge_pairs(txns)
    all_issues.extend(sc_issues)
    all_issues.extend(validate_cc_merchant_rec_dates(txns))

    error_count = sum(1 for i in all_issues if i.severity == "ERROR")
    warning_count = sum(1 for i in all_issues if i.severity == "WARNING")

    valid_transactions = txns if error_count == 0 else []

    return BankRecValidationResult(
        valid_transactions=valid_transactions,
        issues=all_issues,
        error_count=error_count,
        warning_count=warning_count,
    )
