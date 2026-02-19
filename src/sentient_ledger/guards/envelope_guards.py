"""Envelope integrity guards — verify checksums on state envelopes."""

from __future__ import annotations

from sentient_ledger.models.envelope import StateEnvelope


def verify_envelope_integrity(state: dict) -> list[str]:
    """Return list of envelope_ids whose checksums do not match their payloads."""
    failed: list[str] = []
    for envelope_dict in state.get("envelopes", []):
        env = StateEnvelope(**envelope_dict)
        if not env.verify_checksum():
            failed.append(env.envelope_id)
    return failed


def all_envelopes_valid(state: dict) -> bool:
    """Return True if every envelope in state passes checksum verification."""
    return len(verify_envelope_integrity(state)) == 0
