"""Unit tests for audit helper functions."""

from sentient_ledger.agents.audit_helpers import (
    compute_proposal_checksum,
    create_audit_record,
)
from sentient_ledger.models.audit import AuditActor
from sentient_ledger.models.enums import ActorType, AgentId, AuditEventType


class TestComputeProposalChecksum:
    def test_deterministic(self):
        """Same input produces same checksum."""
        proposal = {"proposal_id": "p-001", "amount": "3000"}
        c1 = compute_proposal_checksum(proposal)
        c2 = compute_proposal_checksum(proposal)
        assert c1 == c2
        assert len(c1) == 64  # SHA-256 hex

    def test_changes_with_different_input(self):
        """Different input produces different checksum."""
        p1 = {"proposal_id": "p-001", "amount": "3000"}
        p2 = {"proposal_id": "p-001", "amount": "4000"}
        assert compute_proposal_checksum(p1) != compute_proposal_checksum(p2)


class TestCreateAuditRecord:
    def _actor(self):
        return AuditActor(type=ActorType.AGENT, id=AgentId.PROCESS_MANAGER)

    def test_create_record_no_previous(self):
        """First record in chain has empty previous_record_hash."""
        record = create_audit_record(
            trace_id="t-001",
            proposal_id="p-001",
            event_type=AuditEventType.CREATED,
            actor=self._actor(),
            previous_records=[],
            proposal_checksum="abc123",
        )
        assert record.integrity.previous_record_hash == ""
        assert record.integrity.record_hash != ""
        assert record.integrity.proposal_checksum == "abc123"
        assert record.event_type == AuditEventType.CREATED

    def test_create_record_with_previous(self):
        """Record links to previous record's hash."""
        prev = [{"integrity": {"record_hash": "prevhash123"}}]
        record = create_audit_record(
            trace_id="t-001",
            proposal_id="p-001",
            event_type=AuditEventType.APPROVED,
            actor=self._actor(),
            previous_records=prev,
        )
        assert record.integrity.previous_record_hash == "prevhash123"

    def test_hash_chain_three_records(self):
        """Three records form a valid hash chain."""
        records = []

        r1 = create_audit_record(
            trace_id="t-001",
            proposal_id="p-001",
            event_type=AuditEventType.CREATED,
            actor=self._actor(),
            previous_records=records,
        )
        records.append(r1.model_dump())

        r2 = create_audit_record(
            trace_id="t-001",
            proposal_id="p-001",
            event_type=AuditEventType.APPROVED,
            actor=self._actor(),
            previous_records=records,
        )
        records.append(r2.model_dump())

        r3 = create_audit_record(
            trace_id="t-001",
            proposal_id="p-001",
            event_type=AuditEventType.COMMITTED,
            actor=self._actor(),
            previous_records=records,
        )

        # Chain integrity
        assert r1.integrity.previous_record_hash == ""
        assert r2.integrity.previous_record_hash == r1.integrity.record_hash
        assert r3.integrity.previous_record_hash == r2.integrity.record_hash

    def test_proposal_checksum_deterministic(self):
        """Same proposal dict produces same checksum across records."""
        proposal = {"id": "p-001", "amount": "1000"}
        checksum = compute_proposal_checksum(proposal)

        r1 = create_audit_record(
            trace_id="t-001",
            proposal_id="p-001",
            event_type=AuditEventType.CREATED,
            actor=self._actor(),
            previous_records=[],
            proposal_checksum=checksum,
        )
        r2 = create_audit_record(
            trace_id="t-001",
            proposal_id="p-001",
            event_type=AuditEventType.APPROVED,
            actor=self._actor(),
            previous_records=[r1.model_dump()],
            proposal_checksum=checksum,
        )
        assert r1.integrity.proposal_checksum == r2.integrity.proposal_checksum

    def test_proposal_checksum_changes(self):
        """Different proposals produce different checksums."""
        c1 = compute_proposal_checksum({"amount": "1000"})
        c2 = compute_proposal_checksum({"amount": "2000"})
        assert c1 != c2
