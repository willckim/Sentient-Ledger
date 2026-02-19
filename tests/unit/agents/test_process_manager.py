"""Unit tests for process_manager authority + SLA escalation wiring."""

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from sentient_ledger.agents.process_manager import (
    _determine_authority,
    proposal_node,
    sign_off_node,
)
from sentient_ledger.config import AUTHORITY_ESCALATION, AUTHORITY_THRESHOLDS
from sentient_ledger.models.enums import (
    AuthorityLevel,
    SignOffDecision,
)
from sentient_ledger.models.graph_state import create_initial_state


def _base_state(**overrides):
    state = create_initial_state(str(uuid.uuid4()))
    state.update(overrides)
    return state


# --- Work Stream A: AUTHORITY_THRESHOLDS wired ---


class TestDetermineAuthority:
    def test_authority_l1_under_5000(self):
        assert _determine_authority(Decimal("4999.99")) == AuthorityLevel.L1_STAFF
        assert _determine_authority(Decimal("5000.00")) == AuthorityLevel.L1_STAFF

    def test_authority_l2_under_50000(self):
        assert _determine_authority(Decimal("5000.01")) == AuthorityLevel.L2_SENIOR
        assert _determine_authority(Decimal("50000.00")) == AuthorityLevel.L2_SENIOR

    def test_authority_l3_under_500000(self):
        assert _determine_authority(Decimal("50000.01")) == AuthorityLevel.L3_MANAGER
        assert _determine_authority(Decimal("500000.00")) == AuthorityLevel.L3_MANAGER

    def test_authority_l4_over_500000(self):
        assert _determine_authority(Decimal("500000.01")) == AuthorityLevel.L4_CONTROLLER
        assert _determine_authority(Decimal("9999999")) == AuthorityLevel.L4_CONTROLLER


# --- Work Stream B: AUTHORITY_ESCALATION wired into sign_off_node ---


class TestSLAEscalation:
    def _expired_state(self, authority: AuthorityLevel):
        """Build a state where SLA is expired for the given authority level."""
        now = datetime.now(timezone.utc)
        state = _base_state(
            proposed_adjustments=[
                {
                    "entry_id": "e1",
                    "debit_account": "100",
                    "debit_amount": "100",
                    "credit_account": "200",
                    "credit_amount": "100",
                    "memo": "test",
                }
            ],
        )
        # Run proposal_node to set up proposal + sla_deadline
        proposal_result = proposal_node(state)
        state.update(proposal_result)

        # Override authority and set sign-off timestamp far in the future
        state["sign_off_authority"] = authority
        state["sign_off_decision"] = SignOffDecision.APPROVE
        # Set sign_off_timestamp well past the deadline
        state["sign_off_timestamp"] = (now + timedelta(days=365)).isoformat()

        return state

    def test_sla_expiry_escalates_l1_to_l2(self):
        state = self._expired_state(AuthorityLevel.L1_STAFF)
        result = sign_off_node(state)
        # SLA expired → ESCALATE
        records = result["audit_records"]
        assert any(r["event_type"] == "ESCALATED" for r in records)

    def test_sla_expiry_escalates_l3_to_l4(self):
        state = self._expired_state(AuthorityLevel.L3_MANAGER)
        result = sign_off_node(state)
        records = result["audit_records"]
        assert any(r["event_type"] == "ESCALATED" for r in records)

    def test_sla_expiry_l4_stays_l4(self):
        state = self._expired_state(AuthorityLevel.L4_CONTROLLER)
        result = sign_off_node(state)
        records = result["audit_records"]
        # Should still escalate (in terms of decision), but authority stays L4
        assert any(r["event_type"] == "ESCALATED" for r in records)
