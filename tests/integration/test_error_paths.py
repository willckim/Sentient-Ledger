"""Tests for error/quarantine paths through the graph."""

import uuid

import pytest

from sentient_ledger.graph.builder import build_reconciliation_graph
from sentient_ledger.models.enums import (
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


def _discrepancy_records():
    return [
        {
            "record_id": "rec-001",
            "account": {"code": "1520", "name": "Accum Depr", "category": "ASSET", "sub_category": "fixed", "is_control_account": True},
            "dimensions": {"business_unit": "BU-001", "composite_key": "1520-BU001"},
            "balances": {"opening": "100000", "debits": "50000", "credits": "30000", "closing": "120000"},
            "_discrepancy": {
                "reason": "DEPRECIATION_VARIANCE_EXCEEDS_THRESHOLD",
                "account": "1520",
                "account_name": "Accum Depr",
                "priority": "HIGH",
                "detail": {"expected": "33000", "actual": "36000", "variance": "3000", "variance_pct": 0.09, "period": "2026-01"},
            },
            "period": {"fiscal_year": 2026, "fiscal_period": 1, "calendar_month": "2026-01"},
        },
    ]


class TestIngestQuarantine:
    def test_high_malformed_pct_quarantines(self, graph):
        state = _base_state(malformed_pct=5.0)
        result = graph.invoke(state)
        assert result["current_state"] == LedgerState.ERROR_QUARANTINE

    def test_threshold_boundary_passes(self, graph):
        """Exactly 1% should pass (≤ threshold)."""
        state = _base_state(
            malformed_pct=1.0,
            trial_balance_records=[
                {
                    "record_id": "rec-001",
                    "account": {"code": "1000", "name": "Cash", "category": "ASSET", "sub_category": "current", "is_control_account": False},
                    "dimensions": {"business_unit": "BU-001", "composite_key": "1000-BU001"},
                    "balances": {"opening": "100000", "debits": "50000", "credits": "30000", "closing": "120000"},
                    "period": {"fiscal_year": 2026, "fiscal_period": 1, "calendar_month": "2026-01"},
                },
            ],
        )
        result = graph.invoke(state)
        assert result["current_state"] != LedgerState.ERROR_QUARANTINE

    def test_just_above_threshold_quarantines(self, graph):
        state = _base_state(malformed_pct=1.01)
        result = graph.invoke(state)
        assert result["current_state"] == LedgerState.ERROR_QUARANTINE


class TestSignOffEscalation:
    def test_escalation_quarantines(self, graph):
        state = _base_state(trial_balance_records=_discrepancy_records())
        state["sign_off_decision"] = SignOffDecision.ESCALATE
        result = graph.invoke(state)
        assert result["current_state"] == LedgerState.ERROR_QUARANTINE


class TestCommitFailure:
    def test_nack_quarantines(self, graph):
        state = _base_state(trial_balance_records=_discrepancy_records())
        state["sign_off_decision"] = SignOffDecision.APPROVE
        state["sign_off_authority"] = AuthorityLevel.L4_CONTROLLER
        state["commit_result"] = CommitResult.NACK
        result = graph.invoke(state)
        assert result["current_state"] == LedgerState.ERROR_QUARANTINE

    def test_ack_succeeds(self, graph):
        state = _base_state(trial_balance_records=_discrepancy_records())
        state["sign_off_decision"] = SignOffDecision.APPROVE
        state["sign_off_authority"] = AuthorityLevel.L4_CONTROLLER
        state["commit_result"] = CommitResult.ACK
        result = graph.invoke(state)
        assert result["current_state"] == LedgerState.AUDIT_LOG
