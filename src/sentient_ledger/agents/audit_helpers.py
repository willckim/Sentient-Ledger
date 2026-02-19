"""Audit helper functions for hash-chain integrity and record creation."""

import hashlib
import json

from sentient_ledger.agents.base import new_id, now_iso
from sentient_ledger.models.audit import (
    AuditActor,
    AuditDetail,
    AuditIntegrity,
    AuditRecord,
)
from sentient_ledger.models.enums import AuditEventType


def compute_proposal_checksum(proposal: dict) -> str:
    """SHA-256 checksum of a proposal dict for integrity verification."""
    raw = json.dumps(proposal, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()


def create_audit_record(
    trace_id: str,
    proposal_id: str,
    event_type: AuditEventType,
    actor: AuditActor,
    previous_records: list[dict],
    proposal_checksum: str = "",
    reasoning_snapshot: str = "",
    reviewer_notes: str | None = None,
    rejection_reason: str | None = None,
    time_in_review_ms: int = 0,
) -> AuditRecord:
    """Factory that creates an AuditRecord with hash-chain linking."""
    prev_hash = (
        previous_records[-1].get("integrity", {}).get("record_hash", "")
        if previous_records
        else ""
    )

    record = AuditRecord(
        record_id=new_id(),
        trace_id=trace_id,
        proposal_id=proposal_id,
        event_type=event_type,
        actor=actor,
        timestamp=now_iso(),
        detail=AuditDetail(
            reasoning_snapshot=reasoning_snapshot,
            reviewer_notes=reviewer_notes,
            rejection_reason=rejection_reason,
            time_in_review_ms=time_in_review_ms,
        ),
        integrity=AuditIntegrity(
            previous_record_hash=prev_hash,
            proposal_checksum=proposal_checksum,
        ),
    )
    record.integrity.record_hash = record.compute_hash()
    return record
