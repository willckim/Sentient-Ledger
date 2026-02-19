"""GATE FILE: One test per state transition (15 total).

Each test exercises exactly one transition from the transition table.
"""

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


def _base_state(**overrides):
    state = create_initial_state(str(uuid.uuid4()))
    state["total_rows"] = 100
    state["malformed_pct"] = 0.5
    state.update(overrides)
    return state


# ── Transition 1: INGEST → COMPLIANCE_SCAN (malformed_pct ≤ 1%) ──


def test_t01_ingest_to_compliance_scan(graph):
    """T1: INGEST → COMPLIANCE_SCAN when malformed_pct ≤ 1%."""
    state = _base_state(
        malformed_pct=0.5,
        trial_balance_records=_make_clean_records(),
    )
    result = graph.invoke(state)
    # The graph runs to completion; verify compliance_scan was visited
    assert result.get("compliance_result") is not None
    envelopes = result["envelopes"]
    transitions = [(e["state_from"], e["state_to"]) for e in envelopes]
    assert ("INGEST", "COMPLIANCE_SCAN") in transitions


# ── Transition 2: INGEST → ERROR_QUARANTINE (malformed_pct > 1%) ──


def test_t02_ingest_to_error_quarantine(graph):
    """T2: INGEST → ERROR_QUARANTINE when malformed_pct > 1%."""
    state = _base_state(malformed_pct=5.0)
    result = graph.invoke(state)
    assert result["current_state"] == LedgerState.ERROR_QUARANTINE


# ── Transition 3: COMPLIANCE_SCAN → ASSET_INSPECTION (discrepancy detected) ──


def test_t03_compliance_to_asset_inspection(graph):
    """T3: COMPLIANCE_SCAN → ASSET_INSPECTION when asset discrepancy detected."""
    state = _base_state(trial_balance_records=_make_discrepancy_records())
    state["sign_off_decision"] = SignOffDecision.APPROVE
    state["sign_off_authority"] = AuthorityLevel.L4_CONTROLLER
    state["commit_result"] = CommitResult.ACK
    result = graph.invoke(state)
    assert result.get("inspection_report") is not None
    assert len(result.get("asset_flags", [])) > 0
    envelopes = result["envelopes"]
    transitions = [(e["state_from"], e["state_to"]) for e in envelopes]
    assert ("COMPLIANCE_SCAN", "ASSET_INSPECTION") in transitions


# ── Transition 4: COMPLIANCE_SCAN → ANALYSIS (no discrepancies) ──


def test_t04_compliance_to_analysis(graph):
    """T4: COMPLIANCE_SCAN → ANALYSIS when no asset discrepancies."""
    state = _base_state(trial_balance_records=_make_clean_records())
    result = graph.invoke(state)
    assert len(result.get("asset_flags", [])) == 0
    envelopes = result["envelopes"]
    transitions = [(e["state_from"], e["state_to"]) for e in envelopes]
    assert ("COMPLIANCE_SCAN", "ANALYSIS") in transitions


# ── Transition 5: ASSET_INSPECTION → ANALYSIS (normal findings) ──


def test_t05_asset_inspection_to_analysis(graph):
    """T5: ASSET_INSPECTION → ANALYSIS when normal findings (not self-healable)."""
    state = _base_state(trial_balance_records=_make_discrepancy_records())
    state["sign_off_decision"] = SignOffDecision.APPROVE
    state["sign_off_authority"] = AuthorityLevel.L4_CONTROLLER
    state["commit_result"] = CommitResult.ACK
    result = graph.invoke(state)
    envelopes = result["envelopes"]
    transitions = [(e["state_from"], e["state_to"]) for e in envelopes]
    assert ("ASSET_INSPECTION", "ANALYSIS") in transitions


# ── Transition 6: ASSET_INSPECTION → SELF_HEAL (known pattern, confidence ≥ 0.95) ──


def test_t06_asset_inspection_to_self_heal(graph):
    """T6: ASSET_INSPECTION → SELF_HEAL when known pattern matched with confidence ≥ 0.95."""
    state = _base_state(trial_balance_records=_make_discrepancy_records(self_healable=True, confidence=0.98))
    state["sign_off_decision"] = SignOffDecision.APPROVE
    state["sign_off_authority"] = AuthorityLevel.L4_CONTROLLER
    state["commit_result"] = CommitResult.ACK
    result = graph.invoke(state)
    assert result.get("self_heal_correction") is not None
    envelopes = result["envelopes"]
    transitions = [(e["state_from"], e["state_to"]) for e in envelopes]
    assert ("SELF_HEAL", "PROPOSAL") in transitions


# ── Transition 7: SELF_HEAL → PROPOSAL (correction generated, unconditional) ──


def test_t07_self_heal_to_proposal(graph):
    """T7: SELF_HEAL → PROPOSAL unconditionally after correction generated."""
    state = _base_state(trial_balance_records=_make_discrepancy_records(self_healable=True, confidence=0.98))
    state["sign_off_decision"] = SignOffDecision.APPROVE
    state["sign_off_authority"] = AuthorityLevel.L4_CONTROLLER
    state["commit_result"] = CommitResult.ACK
    result = graph.invoke(state)
    envelopes = result["envelopes"]
    transitions = [(e["state_from"], e["state_to"]) for e in envelopes]
    assert ("SELF_HEAL", "PROPOSAL") in transitions
    assert result.get("current_proposal") is not None


# ── Transition 8: ANALYSIS → PROPOSAL (adjustments identified) ──


def test_t08_analysis_to_proposal(graph):
    """T8: ANALYSIS → PROPOSAL when adjustments are identified."""
    state = _base_state(trial_balance_records=_make_discrepancy_records())
    state["sign_off_decision"] = SignOffDecision.APPROVE
    state["sign_off_authority"] = AuthorityLevel.L4_CONTROLLER
    state["commit_result"] = CommitResult.ACK
    result = graph.invoke(state)
    envelopes = result["envelopes"]
    transitions = [(e["state_from"], e["state_to"]) for e in envelopes]
    assert ("ANALYSIS", "PROPOSAL") in transitions


# ── Transition 9: ANALYSIS → AUDIT_LOG (clean, no adjustments) ──


def test_t09_analysis_to_audit_log(graph):
    """T9: ANALYSIS → AUDIT_LOG when analysis is clean, no adjustments needed."""
    state = _base_state(trial_balance_records=_make_clean_records())
    result = graph.invoke(state)
    assert result["current_state"] == LedgerState.AUDIT_LOG
    envelopes = result["envelopes"]
    transitions = [(e["state_from"], e["state_to"]) for e in envelopes]
    assert ("ANALYSIS", "AUDIT_LOG") in transitions


# ── Transition 10: PROPOSAL → SIGN_OFF (always, unconditional) ──


def test_t10_proposal_to_sign_off(graph):
    """T10: PROPOSAL → SIGN_OFF always (HITL mandatory)."""
    state = _base_state(trial_balance_records=_make_discrepancy_records())
    state["sign_off_decision"] = SignOffDecision.APPROVE
    state["sign_off_authority"] = AuthorityLevel.L4_CONTROLLER
    state["commit_result"] = CommitResult.ACK
    result = graph.invoke(state)
    envelopes = result["envelopes"]
    transitions = [(e["state_from"], e["state_to"]) for e in envelopes]
    assert ("PROPOSAL", "SIGN_OFF") in transitions
    assert result.get("sign_off_attempts", 0) >= 1


# ── Transition 11: SIGN_OFF → COMMIT (approved, authority sufficient) ──


def test_t11_sign_off_to_commit(graph):
    """T11: SIGN_OFF → COMMIT when human approves and authority is sufficient."""
    state = _base_state(trial_balance_records=_make_discrepancy_records())
    state["sign_off_decision"] = SignOffDecision.APPROVE
    state["sign_off_authority"] = AuthorityLevel.L4_CONTROLLER
    state["commit_result"] = CommitResult.ACK
    result = graph.invoke(state)
    envelopes = result["envelopes"]
    transitions = [(e["state_from"], e["state_to"]) for e in envelopes]
    assert ("SIGN_OFF", "COMMIT") in [
        (e["state_from"], e["state_to"]) for e in envelopes
        if e["state_from"] == "SIGN_OFF"
    ]


# ── Transition 12: SIGN_OFF → PROPOSAL (rejected with reason) ──


def test_t12_sign_off_to_proposal(graph):
    """T12: SIGN_OFF → PROPOSAL when human rejects with reason."""
    state = _base_state(trial_balance_records=_make_discrepancy_records())
    state["sign_off_decision"] = SignOffDecision.REJECT
    state["sign_off_reason"] = "Needs more detail"
    state["sign_off_authority"] = AuthorityLevel.L4_CONTROLLER
    state["commit_result"] = CommitResult.ACK
    result = graph.invoke(state)
    # Rejection cycle: first attempt rejected, second auto-approved
    assert result.get("sign_off_attempts", 0) >= 2
    assert result["current_state"] == LedgerState.AUDIT_LOG


# ── Transition 13: SIGN_OFF → ERROR_QUARANTINE (escalated) ──


def test_t13_sign_off_to_error_quarantine(graph):
    """T13: SIGN_OFF → ERROR_QUARANTINE when human escalates."""
    state = _base_state(trial_balance_records=_make_discrepancy_records())
    state["sign_off_decision"] = SignOffDecision.ESCALATE
    result = graph.invoke(state)
    assert result["current_state"] == LedgerState.ERROR_QUARANTINE


# ── Transition 14: COMMIT → AUDIT_LOG (ACK received) ──


def test_t14_commit_to_audit_log(graph):
    """T14: COMMIT → AUDIT_LOG when mutation succeeds (ACK)."""
    state = _base_state(trial_balance_records=_make_discrepancy_records())
    state["sign_off_decision"] = SignOffDecision.APPROVE
    state["sign_off_authority"] = AuthorityLevel.L4_CONTROLLER
    state["commit_result"] = CommitResult.ACK
    result = graph.invoke(state)
    assert result["current_state"] == LedgerState.AUDIT_LOG
    envelopes = result["envelopes"]
    transitions = [(e["state_from"], e["state_to"]) for e in envelopes]
    assert ("COMMIT", "AUDIT_LOG") in transitions


# ── Transition 15: COMMIT → ERROR_QUARANTINE (NACK/timeout) ──


def test_t15_commit_to_error_quarantine(graph):
    """T15: COMMIT → ERROR_QUARANTINE when mutation fails (NACK)."""
    state = _base_state(trial_balance_records=_make_discrepancy_records())
    state["sign_off_decision"] = SignOffDecision.APPROVE
    state["sign_off_authority"] = AuthorityLevel.L4_CONTROLLER
    state["commit_result"] = CommitResult.NACK
    result = graph.invoke(state)
    assert result["current_state"] == LedgerState.ERROR_QUARANTINE
