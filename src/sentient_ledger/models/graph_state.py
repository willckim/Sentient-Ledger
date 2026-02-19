"""ReconciliationState — LangGraph TypedDict with annotated reducers."""

from __future__ import annotations

import operator
from typing import Annotated, Any, TypedDict

from sentient_ledger.models.enums import (
    AuthorityLevel,
    CommitResult,
    LedgerState,
    SignOffDecision,
)


class ReconciliationState(TypedDict, total=False):
    # Core tracking
    trace_id: str
    current_state: LedgerState

    # Append-only envelope list (LangGraph reducer)
    envelopes: Annotated[list[dict[str, Any]], operator.add]

    # Ingest data
    trial_balance_records: list[dict[str, Any]]
    malformed_pct: float
    total_rows: int
    malformed_rows: int

    # Compliance scan output
    compliance_result: dict[str, Any]
    asset_flags: list[str]

    # Asset inspection
    inspection_request: dict[str, Any]
    inspection_report: dict[str, Any]

    # Self-heal
    self_heal_correction: dict[str, Any]

    # Analysis
    analysis_result: dict[str, Any]
    proposed_adjustments: list[dict[str, Any]]

    # Proposal
    current_proposal: dict[str, Any]
    proposal_created_at: str
    sla_deadline: str
    proposal_history: Annotated[list[dict[str, Any]], operator.add]

    # Sign-off
    sign_off_decision: SignOffDecision
    sign_off_reason: str
    sign_off_authority: AuthorityLevel
    sign_off_attempts: int
    sign_off_reviewer_notes: str
    sign_off_timestamp: str
    sign_off_actor_id: str

    # Commit
    commit_result: CommitResult

    # Audit
    audit_records: Annotated[list[dict[str, Any]], operator.add]

    # Error info
    error_detail: str

    # Eval data (optional, activates detector path in asset warden)
    asset_register: list[dict[str, Any]]
    gl_balances: list[dict[str, Any]]
    depreciation_schedule: list[dict[str, Any]]


def create_initial_state(trace_id: str) -> ReconciliationState:
    """Create a fresh reconciliation state."""
    return ReconciliationState(
        trace_id=trace_id,
        current_state=LedgerState.INGEST,
        envelopes=[],
        trial_balance_records=[],
        malformed_pct=0.0,
        total_rows=0,
        malformed_rows=0,
        asset_flags=[],
        proposed_adjustments=[],
        sign_off_attempts=0,
        proposal_history=[],
        audit_records=[],
        error_detail="",
    )
