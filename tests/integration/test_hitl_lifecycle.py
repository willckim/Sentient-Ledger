"""Integration tests for the HITL lifecycle audit trail."""

import uuid

import pytest

from sentient_ledger.agents.audit_helpers import compute_proposal_checksum
from sentient_ledger.graph.builder import build_reconciliation_graph
from sentient_ledger.models.enums import (
    AuditEventType,
    AuthorityLevel,
    CommitResult,
    LedgerState,
    SignOffDecision,
)
from sentient_ledger.models.graph_state import create_initial_state


@pytest.fixture
def graph():
    return build_reconciliation_graph()


def _base_state(**overrides):
    state = create_initial_state(str(uuid.uuid4()))
    state["total_rows"] = 100
    state["malformed_pct"] = 0.5
    state.update(overrides)
    return state


def _make_discrepancy_records(self_healable=False, confidence=0.5):
    disc = {
        "reason": "DEPRECIATION_VARIANCE_EXCEEDS_THRESHOLD",
        "account": "1520",
        "account_name": "Accum Depr",
        "priority": "HIGH",
        "detail": {"expected": "33000", "actual": "36000", "variance": "3000", "variance_pct": 0.09, "period": "2026-01"},
    }
    if self_healable:
        disc["_self_healable"] = True
        disc["_confidence"] = confidence
    return [
        {
            "record_id": "rec-001",
            "account": {"code": "1520", "name": "Accum Depr", "category": "ASSET", "sub_category": "fixed", "is_control_account": True},
            "dimensions": {"business_unit": "BU-001", "composite_key": "1520-BU001"},
            "balances": {"opening": "100000", "debits": "50000", "credits": "30000", "closing": "120000"},
            "_discrepancy": disc,
            "period": {"fiscal_year": 2026, "fiscal_period": 1, "calendar_month": "2026-01"},
        },
    ]


def _make_clean_records():
    return [
        {
            "record_id": "rec-001",
            "account": {"code": "1000", "name": "Cash", "category": "ASSET", "sub_category": "current", "is_control_account": False},
            "dimensions": {"business_unit": "BU-001", "composite_key": "1000-BU001"},
            "balances": {"opening": "100000", "debits": "50000", "credits": "30000", "closing": "120000"},
            "period": {"fiscal_year": 2026, "fiscal_period": 1, "calendar_month": "2026-01"},
        },
    ]


def _verify_hash_chain(records):
    """Verify that audit records form a valid hash chain."""
    for i, record in enumerate(records):
        if i == 0:
            assert record["integrity"]["previous_record_hash"] == "", \
                f"First record should have empty prev hash, got: {record['integrity']['previous_record_hash']}"
        else:
            expected_prev = records[i - 1]["integrity"]["record_hash"]
            actual_prev = record["integrity"]["previous_record_hash"]
            assert actual_prev == expected_prev, \
                f"Record {i} prev_hash mismatch: expected {expected_prev}, got {actual_prev}"
        assert record["integrity"]["record_hash"] != "", \
            f"Record {i} should have a record_hash"


class TestHappyPathFullAuditTrail:
    """CREATED -> APPROVED -> COMMITTED with hash chain intact."""

    def test_happy_path_full_audit_trail(self, graph):
        state = _base_state(
            sign_off_decision=SignOffDecision.APPROVE,
            sign_off_authority=AuthorityLevel.L4_CONTROLLER,
            commit_result=CommitResult.ACK,
            trial_balance_records=_make_discrepancy_records(),
        )
        result = graph.invoke(state)
        assert result["current_state"] == LedgerState.AUDIT_LOG

        records = result["audit_records"]
        assert len(records) >= 3

        event_types = [r["event_type"] for r in records]
        assert AuditEventType.CREATED in event_types
        assert AuditEventType.APPROVED in event_types
        assert AuditEventType.COMMITTED in event_types

        # Verify order: CREATED before APPROVED before COMMITTED
        created_idx = event_types.index(AuditEventType.CREATED)
        approved_idx = event_types.index(AuditEventType.APPROVED)
        committed_idx = event_types.index(AuditEventType.COMMITTED)
        assert created_idx < approved_idx < committed_idx

        # Hash chain intact
        _verify_hash_chain(records)


class TestRejectionCycleAuditTrail:
    """CREATED -> REJECTED -> CREATED -> APPROVED -> COMMITTED."""

    def test_rejection_cycle_audit_trail(self, graph):
        state = _base_state(
            sign_off_decision=SignOffDecision.REJECT,
            sign_off_reason="Needs more detail",
            sign_off_authority=AuthorityLevel.L4_CONTROLLER,
            commit_result=CommitResult.ACK,
            trial_balance_records=_make_discrepancy_records(),
        )
        result = graph.invoke(state)
        assert result["current_state"] == LedgerState.AUDIT_LOG

        records = result["audit_records"]
        event_types = [r["event_type"] for r in records]
        # Should have: CREATED, REJECTED, CREATED (re-draft), APPROVED (auto), COMMITTED
        assert len(records) >= 5
        assert event_types.count(AuditEventType.CREATED) >= 2
        assert AuditEventType.REJECTED in event_types
        assert AuditEventType.APPROVED in event_types
        assert AuditEventType.COMMITTED in event_types

        _verify_hash_chain(records)


class TestEscalationAuditTrail:
    """CREATED -> ESCALATED -> ends ERROR_QUARANTINE."""

    def test_escalation_audit_trail(self, graph):
        state = _base_state(
            sign_off_decision=SignOffDecision.ESCALATE,
            sign_off_authority=AuthorityLevel.L4_CONTROLLER,
            trial_balance_records=_make_discrepancy_records(),
        )
        result = graph.invoke(state)
        assert result["current_state"] == LedgerState.ERROR_QUARANTINE

        records = result["audit_records"]
        event_types = [r["event_type"] for r in records]
        assert AuditEventType.CREATED in event_types
        assert AuditEventType.ESCALATED in event_types
        assert len(records) >= 2


class TestSLAExpiryAutoEscalation:
    def test_sla_expiry_auto_escalation(self, graph):
        """When sign_off_timestamp exceeds sla_deadline, decision becomes ESCALATE."""
        state = _base_state(
            sign_off_decision=SignOffDecision.APPROVE,
            sign_off_authority=AuthorityLevel.L4_CONTROLLER,
            trial_balance_records=_make_discrepancy_records(),
            # Force SLA expiry: sign-off happens far in the future, past any SLA deadline
            sign_off_timestamp="2099-01-01T00:00:00+00:00",
        )
        result = graph.invoke(state)
        # With SLA expired, decision should become ESCALATE -> ERROR_QUARANTINE
        assert result["current_state"] == LedgerState.ERROR_QUARANTINE
        records = result["audit_records"]
        event_types = [r["event_type"] for r in records]
        assert AuditEventType.ESCALATED in event_types


class TestCleanPathSingleCommitted:
    def test_clean_path_single_committed(self, graph):
        """No proposal path -> only 1 COMMITTED record."""
        state = _base_state(trial_balance_records=_make_clean_records())
        result = graph.invoke(state)
        assert result["current_state"] == LedgerState.AUDIT_LOG
        records = result["audit_records"]
        assert len(records) == 1
        assert records[0]["event_type"] == AuditEventType.COMMITTED


class TestAuthorityLevelEnforcement:
    def test_authority_level_enforcement(self, graph):
        """Proposal sets authority level based on amount."""
        state = _base_state(
            sign_off_decision=SignOffDecision.APPROVE,
            sign_off_authority=AuthorityLevel.L4_CONTROLLER,
            commit_result=CommitResult.ACK,
            trial_balance_records=_make_discrepancy_records(),
        )
        result = graph.invoke(state)
        proposal = result["current_proposal"]
        # 3000 amount -> L1_STAFF
        assert proposal["required_approval"]["authority_level"] == AuthorityLevel.L1_STAFF


class TestReasoningChainPopulatedE2E:
    def test_reasoning_chain_populated_e2e(self, graph):
        """Reasoning chain is populated with inspection data in full flow."""
        state = _base_state(
            sign_off_decision=SignOffDecision.APPROVE,
            sign_off_authority=AuthorityLevel.L4_CONTROLLER,
            commit_result=CommitResult.ACK,
            trial_balance_records=_make_discrepancy_records(),
        )
        result = graph.invoke(state)
        chain = result["current_proposal"]["reasoning_chain"]
        assert chain is not None
        assert len(chain["logic_steps"]) >= 1
        assert chain["confidence"] > 0
        assert chain["risk_assessment"] != ""


class TestProposalChecksumConsistentAcrossLifecycle:
    def test_proposal_checksum_consistent_across_lifecycle(self, graph):
        """The proposal checksum in CREATED and COMMITTED records should match
        because it's the same proposal."""
        state = _base_state(
            sign_off_decision=SignOffDecision.APPROVE,
            sign_off_authority=AuthorityLevel.L4_CONTROLLER,
            commit_result=CommitResult.ACK,
            trial_balance_records=_make_discrepancy_records(),
        )
        result = graph.invoke(state)
        records = result["audit_records"]
        checksums = [r["integrity"]["proposal_checksum"] for r in records if r["integrity"]["proposal_checksum"]]
        # All checksums should be the same proposal
        assert len(set(checksums)) == 1


class TestSelfHealPathFullAuditTrail:
    def test_self_heal_path_full_audit_trail(self, graph):
        """Self-heal path should produce CREATED -> APPROVED -> COMMITTED."""
        state = _base_state(
            sign_off_decision=SignOffDecision.APPROVE,
            sign_off_authority=AuthorityLevel.L4_CONTROLLER,
            commit_result=CommitResult.ACK,
            trial_balance_records=_make_discrepancy_records(self_healable=True, confidence=0.98),
        )
        result = graph.invoke(state)
        assert result["current_state"] == LedgerState.AUDIT_LOG

        records = result["audit_records"]
        event_types = [r["event_type"] for r in records]
        assert AuditEventType.CREATED in event_types
        assert AuditEventType.APPROVED in event_types
        assert AuditEventType.COMMITTED in event_types
        assert len(records) >= 3

        _verify_hash_chain(records)
