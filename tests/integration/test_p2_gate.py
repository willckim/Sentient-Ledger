"""P2 GATE: End-to-end human sign-off with full audit chain verification."""

import uuid

import pytest

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


def test_p2_gate_end_to_end_human_signoff(graph):
    """P2 Gate: full graph run with human sign-off demonstrated.

    Asserts:
    - audit_records >= 3 (CREATED + APPROVED + COMMITTED)
    - Hash chain intact
    - At least one HUMAN actor
    - Reasoning chain non-empty
    - SLA hours > 0
    """
    state = create_initial_state(str(uuid.uuid4()))
    state["total_rows"] = 100
    state["malformed_pct"] = 0.5
    state["sign_off_decision"] = SignOffDecision.APPROVE
    state["sign_off_authority"] = AuthorityLevel.L4_CONTROLLER
    state["commit_result"] = CommitResult.ACK
    state["trial_balance_records"] = [
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

    result = graph.invoke(state)

    # Terminal state
    assert result["current_state"] == LedgerState.AUDIT_LOG

    # Audit records: >= 3 (CREATED, APPROVED, COMMITTED)
    records = result["audit_records"]
    assert len(records) >= 3, f"Expected >= 3 audit records, got {len(records)}"

    event_types = [r["event_type"] for r in records]
    assert AuditEventType.CREATED in event_types
    assert AuditEventType.APPROVED in event_types
    assert AuditEventType.COMMITTED in event_types

    # Hash chain integrity
    for i, record in enumerate(records):
        if i == 0:
            assert record["integrity"]["previous_record_hash"] == ""
        else:
            assert record["integrity"]["previous_record_hash"] == records[i - 1]["integrity"]["record_hash"]
        assert record["integrity"]["record_hash"] != ""

    # At least one HUMAN actor
    actor_types = [r["actor"]["type"] for r in records]
    assert "HUMAN" in actor_types

    # Reasoning chain non-empty
    proposal = result["current_proposal"]
    chain = proposal.get("reasoning_chain")
    assert chain is not None
    assert chain.get("confidence", 0) > 0
    assert chain.get("risk_assessment", "") != ""

    # SLA hours > 0
    sla_hours = proposal["required_approval"]["sla_hours"]
    assert sla_hours > 0
