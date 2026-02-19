"""Shared helpers for agent stubs."""

import uuid
from datetime import datetime, timezone

from sentient_ledger.models.enums import AgentId, LedgerState
from sentient_ledger.models.envelope import StateEnvelope


def make_envelope(
    source_agent: AgentId,
    target_agent: AgentId,
    state_from: LedgerState,
    state_to: LedgerState,
    payload: dict,
    trace_id: str,
    parent_envelope_id: str | None = None,
) -> dict:
    """Build an envelope dict with computed checksum."""
    env = StateEnvelope(
        envelope_id=str(uuid.uuid4()),
        trace_id=trace_id,
        parent_envelope_id=parent_envelope_id,
        source_agent=source_agent,
        target_agent=target_agent,
        state_from=state_from,
        state_to=state_to,
        payload=payload,
        timestamp=datetime.now(timezone.utc).isoformat(),
    ).with_checksum()
    return env.model_dump()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id() -> str:
    return str(uuid.uuid4())
