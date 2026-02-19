"""End-to-end happy path tests through the full graph."""

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


class TestCleanHappyPath:
    """INGEST → COMPLIANCE_SCAN → ANALYSIS → AUDIT_LOG (no issues found)."""

    def test_ends_at_audit_log(self, graph):
        state = _base_state(trial_balance_records=[
            {
                "record_id": "rec-001",
                "account": {"code": "1000", "name": "Cash", "category": "ASSET", "sub_category": "current", "is_control_account": False},
                "dimensions": {"business_unit": "BU-001", "composite_key": "1000-BU001"},
                "balances": {"opening": "100000", "debits": "50000", "credits": "30000", "closing": "120000"},
                "period": {"fiscal_year": 2026, "fiscal_period": 1, "calendar_month": "2026-01"},
            },
        ])
        result = graph.invoke(state)
        assert result["current_state"] == LedgerState.AUDIT_LOG

    def test_clean_path_has_audit_record(self, graph):
        state = _base_state(trial_balance_records=[
            {
                "record_id": "rec-001",
                "account": {"code": "1000", "name": "Cash", "category": "ASSET", "sub_category": "current", "is_control_account": False},
                "dimensions": {"business_unit": "BU-001", "composite_key": "1000-BU001"},
                "balances": {"opening": "100000", "debits": "50000", "credits": "30000", "closing": "120000"},
                "period": {"fiscal_year": 2026, "fiscal_period": 1, "calendar_month": "2026-01"},
            },
        ])
        result = graph.invoke(state)
        assert len(result.get("audit_records", [])) >= 1

    def test_clean_path_no_proposal(self, graph):
        state = _base_state(trial_balance_records=[
            {
                "record_id": "rec-001",
                "account": {"code": "1000", "name": "Cash", "category": "ASSET", "sub_category": "current", "is_control_account": False},
                "dimensions": {"business_unit": "BU-001", "composite_key": "1000-BU001"},
                "balances": {"opening": "100000", "debits": "50000", "credits": "30000", "closing": "120000"},
                "period": {"fiscal_year": 2026, "fiscal_period": 1, "calendar_month": "2026-01"},
            },
        ])
        result = graph.invoke(state)
        assert result.get("current_proposal") is None

    def test_clean_path_envelopes_trace(self, graph):
        state = _base_state(trial_balance_records=[
            {
                "record_id": "rec-001",
                "account": {"code": "1000", "name": "Cash", "category": "ASSET", "sub_category": "current", "is_control_account": False},
                "dimensions": {"business_unit": "BU-001", "composite_key": "1000-BU001"},
                "balances": {"opening": "100000", "debits": "50000", "credits": "30000", "closing": "120000"},
                "period": {"fiscal_year": 2026, "fiscal_period": 1, "calendar_month": "2026-01"},
            },
        ])
        result = graph.invoke(state)
        envelopes = result["envelopes"]
        # All envelopes share the same trace_id
        trace_ids = {e["trace_id"] for e in envelopes}
        assert len(trace_ids) == 1


class TestDiscrepancyHappyPath:
    """INGEST → COMPLIANCE → ASSET_INSPECTION → ANALYSIS → PROPOSAL → SIGN_OFF → COMMIT → AUDIT_LOG."""

    def _discrepancy_state(self):
        return _base_state(
            sign_off_decision=SignOffDecision.APPROVE,
            sign_off_authority=AuthorityLevel.L4_CONTROLLER,
            commit_result=CommitResult.ACK,
            trial_balance_records=[
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
            ],
        )

    def test_ends_at_audit_log(self, graph):
        result = graph.invoke(self._discrepancy_state())
        assert result["current_state"] == LedgerState.AUDIT_LOG

    def test_visits_all_expected_states(self, graph):
        result = graph.invoke(self._discrepancy_state())
        envelopes = result["envelopes"]
        visited_from = {e["state_from"] for e in envelopes}
        assert "INGEST" in visited_from
        assert "COMPLIANCE_SCAN" in visited_from
        assert "ASSET_INSPECTION" in visited_from
        assert "ANALYSIS" in visited_from
        assert "PROPOSAL" in visited_from
        assert "SIGN_OFF" in visited_from
        assert "COMMIT" in visited_from

    def test_has_proposal(self, graph):
        result = graph.invoke(self._discrepancy_state())
        assert result.get("current_proposal") is not None

    def test_has_audit_record(self, graph):
        result = graph.invoke(self._discrepancy_state())
        assert len(result.get("audit_records", [])) >= 1

    def test_envelopes_have_checksums(self, graph):
        result = graph.invoke(self._discrepancy_state())
        for env in result["envelopes"]:
            assert env.get("checksum"), f"Envelope {env.get('envelope_id')} missing checksum"


class TestSelfHealHappyPath:
    """INGEST → COMPLIANCE → ASSET_INSPECTION → SELF_HEAL → PROPOSAL → SIGN_OFF → COMMIT → AUDIT_LOG."""

    def _self_heal_state(self):
        return _base_state(
            sign_off_decision=SignOffDecision.APPROVE,
            sign_off_authority=AuthorityLevel.L4_CONTROLLER,
            commit_result=CommitResult.ACK,
            trial_balance_records=[
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
                        "_self_healable": True,
                        "_confidence": 0.98,
                        "detail": {"expected": "33000", "actual": "36000", "variance": "3000", "variance_pct": 0.09, "period": "2026-01"},
                    },
                    "period": {"fiscal_year": 2026, "fiscal_period": 1, "calendar_month": "2026-01"},
                },
            ],
        )

    def test_ends_at_audit_log(self, graph):
        result = graph.invoke(self._self_heal_state())
        assert result["current_state"] == LedgerState.AUDIT_LOG

    def test_visits_self_heal(self, graph):
        result = graph.invoke(self._self_heal_state())
        envelopes = result["envelopes"]
        visited_from = {e["state_from"] for e in envelopes}
        assert "SELF_HEAL" in visited_from

    def test_has_self_heal_correction(self, graph):
        result = graph.invoke(self._self_heal_state())
        assert result.get("self_heal_correction") is not None


class TestRejectionCyclePath:
    """SIGN_OFF rejects → PROPOSAL (re-draft) → SIGN_OFF auto-approves → COMMIT → AUDIT_LOG."""

    def test_rejection_cycle_terminates(self, graph):
        state = _base_state(
            sign_off_decision=SignOffDecision.REJECT,
            sign_off_reason="Needs more detail",
            sign_off_authority=AuthorityLevel.L4_CONTROLLER,
            commit_result=CommitResult.ACK,
            trial_balance_records=[
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
            ],
        )
        result = graph.invoke(state)
        assert result["current_state"] == LedgerState.AUDIT_LOG
        assert result.get("sign_off_attempts", 0) >= 2
