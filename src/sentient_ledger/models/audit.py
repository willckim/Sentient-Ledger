"""Audit record model with hash-chain integrity."""

import hashlib
import json

from pydantic import BaseModel

from sentient_ledger.models.enums import ActorType, AuditEventType, AuthorityLevel


class AuditActor(BaseModel):
    type: ActorType
    id: str
    role: str = ""
    authority_level: AuthorityLevel = AuthorityLevel.L1_STAFF


class AuditDetail(BaseModel):
    reasoning_snapshot: str = ""
    reviewer_notes: str | None = None
    rejection_reason: str | None = None
    time_in_review_ms: int = 0


class AuditIntegrity(BaseModel):
    previous_record_hash: str = ""
    record_hash: str = ""
    proposal_checksum: str = ""


class AuditRecord(BaseModel):
    record_id: str
    trace_id: str
    proposal_id: str = ""
    event_type: AuditEventType
    actor: AuditActor
    timestamp: str
    detail: AuditDetail = AuditDetail()
    integrity: AuditIntegrity = AuditIntegrity()

    def compute_hash(self) -> str:
        data = self.model_dump(exclude={"integrity"})
        raw = json.dumps(data, sort_keys=True, default=str)
        return hashlib.sha256(raw.encode()).hexdigest()
