"""Audit chain integration for the bank reconciliation module.

Delegates to the existing create_audit_record() from agents/audit_helpers.py so
that bank rec audit records participate in the same SHA-256 hash chain.
"""

from __future__ import annotations

import json

from sentient_ledger.agents.audit_helpers import create_audit_record
from sentient_ledger.agents.base import new_id, now_iso
from sentient_ledger.models.audit import AuditActor, AuditRecord
from sentient_ledger.models.bank_reconciliation import (
    BankRecValidationResult,
    ReconciliationBatch,
)
from sentient_ledger.models.enums import ActorType, AuditEventType, AuthorityLevel


def _bank_rec_actor() -> AuditActor:
    """Standard actor for automated bank rec operations."""
    return AuditActor(
        type=ActorType.AGENT,
        id="BANK_REC_AGENT",
        role="bank_reconciliation",
        authority_level=AuthorityLevel.L1_STAFF,
    )


def create_batch_audit_record(
    batch: ReconciliationBatch,
    event_type: AuditEventType,
    previous_records: list[dict],
    reasoning_snapshot: str = "",
) -> AuditRecord:
    """Create an audit record for a ReconciliationBatch, chaining into previous_records."""
    proposal_checksum = _batch_checksum(batch)
    return create_audit_record(
        trace_id=batch.batch_id,
        proposal_id=batch.batch_id,
        event_type=event_type,
        actor=_bank_rec_actor(),
        previous_records=previous_records,
        proposal_checksum=proposal_checksum,
        reasoning_snapshot=reasoning_snapshot,
    )


def create_validation_audit_record(
    batch_id: str,
    validation_result: BankRecValidationResult,
    previous_records: list[dict],
) -> AuditRecord:
    """Create an audit record capturing the validation result snapshot."""
    snapshot = json.dumps(
        {
            "error_count": validation_result.error_count,
            "warning_count": validation_result.warning_count,
            "valid_transaction_count": len(validation_result.valid_transactions),
            "issue_rules": [i.rule for i in validation_result.issues],
        },
        sort_keys=True,
    )
    return create_audit_record(
        trace_id=batch_id,
        proposal_id=batch_id,
        event_type=AuditEventType.VIEWED,
        actor=_bank_rec_actor(),
        previous_records=previous_records,
        reasoning_snapshot=snapshot,
    )


def _batch_checksum(batch: ReconciliationBatch) -> str:
    """SHA-256 of key batch fields for integrity verification."""
    import hashlib

    data = {
        "batch_id": batch.batch_id,
        "workflow": batch.workflow.value,
        "total_rows": batch.total_rows,
        "new_rows": batch.new_rows,
        "opening_balance": str(batch.opening_balance),
        "closing_balance": str(batch.closing_balance),
        "status": batch.status.value,
    }
    raw = json.dumps(data, sort_keys=True)
    return hashlib.sha256(raw.encode()).hexdigest()
