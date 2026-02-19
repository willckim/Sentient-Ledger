"""State envelope — typed wrapper for inter-agent communication."""

import hashlib
import json
from typing import Any, Generic, TypeVar

from pydantic import BaseModel

from sentient_ledger.config import SCHEMA_VERSION
from sentient_ledger.models.enums import AgentId, LedgerState

T = TypeVar("T", bound=BaseModel)


class StateEnvelope(BaseModel, Generic[T]):
    envelope_id: str
    trace_id: str
    parent_envelope_id: str | None = None
    source_agent: AgentId
    target_agent: AgentId
    state_from: LedgerState
    state_to: LedgerState
    payload: Any  # T after model_dump
    timestamp: str
    checksum: str = ""
    schema_version: str = SCHEMA_VERSION

    def compute_checksum(self) -> str:
        raw = json.dumps(self.payload, sort_keys=True, default=str)
        return hashlib.sha256(raw.encode()).hexdigest()

    def with_checksum(self) -> "StateEnvelope[T]":
        self.checksum = self.compute_checksum()
        return self

    def verify_checksum(self) -> bool:
        """Return True if the current checksum matches the recomputed one."""
        if not self.checksum:
            return False
        return self.checksum == self.compute_checksum()


class EnvelopeIntegrityError(Exception):
    """Raised when envelope checksum verification fails."""
