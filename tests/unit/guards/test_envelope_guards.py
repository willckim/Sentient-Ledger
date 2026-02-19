"""Unit tests for envelope integrity guards."""

import hashlib
import json
import uuid
from datetime import datetime, timezone

import pytest

from sentient_ledger.guards.envelope_guards import (
    all_envelopes_valid,
    verify_envelope_integrity,
)
from sentient_ledger.models.envelope import (
    EnvelopeIntegrityError,
    StateEnvelope,
)
from sentient_ledger.models.enums import AgentId, LedgerState


def _make_envelope(payload: dict | None = None) -> dict:
    """Create a valid envelope dict with correct checksum."""
    if payload is None:
        payload = {"key": "value"}
    env = StateEnvelope(
        envelope_id=str(uuid.uuid4()),
        trace_id="test-trace",
        source_agent=AgentId.SYSTEM,
        target_agent=AgentId.COMPLIANCE_SPECIALIST,
        state_from=LedgerState.INGEST,
        state_to=LedgerState.COMPLIANCE_SCAN,
        payload=payload,
        timestamp=datetime.now(timezone.utc).isoformat(),
    ).with_checksum()
    return env.model_dump()


class TestVerifyChecksum:
    def test_verify_checksum_method_true(self):
        env = StateEnvelope(
            envelope_id="e1",
            trace_id="t1",
            source_agent=AgentId.SYSTEM,
            target_agent=AgentId.SYSTEM,
            state_from=LedgerState.INGEST,
            state_to=LedgerState.INGEST,
            payload={"x": 1},
            timestamp="2024-01-01T00:00:00",
        ).with_checksum()
        assert env.verify_checksum() is True

    def test_verify_checksum_method_false(self):
        env = StateEnvelope(
            envelope_id="e1",
            trace_id="t1",
            source_agent=AgentId.SYSTEM,
            target_agent=AgentId.SYSTEM,
            state_from=LedgerState.INGEST,
            state_to=LedgerState.INGEST,
            payload={"x": 1},
            timestamp="2024-01-01T00:00:00",
        ).with_checksum()
        env.payload = {"x": 999}  # tamper
        assert env.verify_checksum() is False


class TestEnvelopeGuards:
    def test_valid_envelope_passes(self):
        state = {"envelopes": [_make_envelope()]}
        assert verify_envelope_integrity(state) == []

    def test_tampered_payload_fails(self):
        env_dict = _make_envelope()
        env_dict["payload"] = {"tampered": True}
        state = {"envelopes": [env_dict]}
        failed = verify_envelope_integrity(state)
        assert len(failed) == 1
        assert failed[0] == env_dict["envelope_id"]

    def test_empty_checksum_fails(self):
        env_dict = _make_envelope()
        env_dict["checksum"] = ""
        state = {"envelopes": [env_dict]}
        failed = verify_envelope_integrity(state)
        assert len(failed) == 1

    def test_no_envelopes_passes(self):
        assert verify_envelope_integrity({"envelopes": []}) == []
        assert verify_envelope_integrity({}) == []

    def test_multiple_envelopes_mixed(self):
        good = _make_envelope({"a": 1})
        bad = _make_envelope({"b": 2})
        bad["payload"] = {"b": 999}
        state = {"envelopes": [good, bad]}
        failed = verify_envelope_integrity(state)
        assert len(failed) == 1
        assert failed[0] == bad["envelope_id"]

    def test_envelope_integrity_error_raised(self):
        """EnvelopeIntegrityError can be raised and caught."""
        with pytest.raises(EnvelopeIntegrityError):
            raise EnvelopeIntegrityError("test corruption")

    def test_all_envelopes_valid_guard_true(self):
        state = {"envelopes": [_make_envelope(), _make_envelope({"x": 42})]}
        assert all_envelopes_valid(state) is True

    def test_all_envelopes_valid_guard_false(self):
        env = _make_envelope()
        env["payload"] = {"corrupted": True}
        state = {"envelopes": [env]}
        assert all_envelopes_valid(state) is False
