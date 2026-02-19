"""Process Manager agent stubs.

Handles: proposal formatting, sign-off, commit, audit logging,
error quarantine, and self-heal nodes.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sentient_ledger.agents.audit_helpers import (
    compute_proposal_checksum,
    create_audit_record,
)
from sentient_ledger.agents.base import make_envelope, new_id, now_iso
from sentient_ledger.config import (
    AUTHORITY_ESCALATION,
    AUTHORITY_SLA_HOURS,
    AUTHORITY_THRESHOLDS,
)
from sentient_ledger.models.audit import (
    AuditActor,
    AuditDetail,
    AuditIntegrity,
    AuditRecord,
)
from sentient_ledger.models.enums import (
    ActorType,
    AgentId,
    AuditEventType,
    AuthorityLevel,
    CommitResult,
    LedgerState,
    ProposalStatus,
    SignOffDecision,
)
from sentient_ledger.models.graph_state import ReconciliationState
from sentient_ledger.models.proposal import (
    AdjustmentProposal,
    JournalEntry,
    ReasoningChain,
    ReasoningStep,
    RequiredApproval,
    TotalImpact,
)


def _determine_authority(total: Decimal) -> AuthorityLevel:
    for level, threshold in sorted(
        AUTHORITY_THRESHOLDS.items(), key=lambda x: (x[1] is None, x[1] or 0)
    ):
        if threshold is None or total <= threshold:
            return level
    return AuthorityLevel.L4_CONTROLLER


def _build_reasoning_steps(state: ReconciliationState) -> list[ReasoningStep]:
    """Build reasoning steps from the data collected across the pipeline."""
    steps: list[ReasoningStep] = []
    step_num = 1

    inspection_request = state.get("inspection_request")
    if inspection_request:
        steps.append(ReasoningStep(
            step_number=step_num,
            action="Compliance scan triggered inspection",
            input_ref="inspection_request",
            output_summary=f"Trigger: {inspection_request.get('trigger_reason', 'unknown')}",
        ))
        step_num += 1

    inspection_report = state.get("inspection_report")
    if inspection_report:
        findings = inspection_report.get("findings", [])
        steps.append(ReasoningStep(
            step_number=step_num,
            action="Asset inspection completed",
            input_ref="inspection_report",
            output_summary=f"{len(findings)} finding(s) identified",
        ))
        step_num += 1

    self_heal = state.get("self_heal_correction")
    if self_heal:
        steps.append(ReasoningStep(
            step_number=step_num,
            action="Self-heal correction applied",
            input_ref="self_heal_correction",
            output_summary=f"Pattern {self_heal.get('pattern_id', 'unknown')}",
        ))
        step_num += 1

    analysis_result = state.get("analysis_result")
    if analysis_result:
        steps.append(ReasoningStep(
            step_number=step_num,
            action="Financial analysis completed",
            input_ref="analysis_result",
            output_summary=f"{analysis_result.get('adjustments', 0)} adjustment(s) proposed",
        ))
        step_num += 1

    return steps


def _compute_confidence(state: ReconciliationState) -> float:
    """Compute confidence from inspection findings."""
    report = state.get("inspection_report", {})
    findings = report.get("findings", [])
    if not findings:
        return 0.85  # default for clean path
    confidences = [f.get("confidence", 0.8) for f in findings]
    return sum(confidences) / len(confidences)


def _assess_risk(total: Decimal, authority: AuthorityLevel) -> str:
    """Simple risk assessment based on amount and authority."""
    if authority == AuthorityLevel.L4_CONTROLLER:
        return "HIGH — requires controller approval"
    if authority == AuthorityLevel.L3_MANAGER:
        return "MEDIUM — requires manager approval"
    if authority == AuthorityLevel.L2_SENIOR:
        return "LOW — requires senior approval"
    return "MINIMAL — staff-level approval sufficient"


def _compute_sla_deadline(created_at: str, authority: AuthorityLevel) -> str:
    """Compute SLA deadline from created_at + SLA hours for authority level."""
    sla_hours = AUTHORITY_SLA_HOURS.get(authority, 4.0)
    dt = datetime.fromisoformat(created_at)
    deadline = dt + timedelta(hours=sla_hours)
    return deadline.isoformat()


def ingest_node(state: ReconciliationState) -> dict:
    """INGEST node: validates data and sets malformed_pct.

    Stub: reads pre-populated malformed_pct from state.
    """
    trace_id = state.get("trace_id", "")
    envelope = make_envelope(
        source_agent=AgentId.SYSTEM,
        target_agent=AgentId.COMPLIANCE_SPECIALIST,
        state_from=LedgerState.INGEST,
        state_to=LedgerState.COMPLIANCE_SCAN,
        payload={"total_rows": state.get("total_rows", 0), "malformed_pct": state.get("malformed_pct", 0.0)},
        trace_id=trace_id,
    )
    return {
        "current_state": LedgerState.INGEST,
        "envelopes": [envelope],
    }


def proposal_node(state: ReconciliationState) -> dict:
    """PROPOSAL node: format adjustments into a formal proposal with reasoning chain."""
    trace_id = state.get("trace_id", "")
    adjustments = state.get("proposed_adjustments", [])
    attempts = state.get("sign_off_attempts", 0)
    previous_records = state.get("audit_records", [])

    total = sum(Decimal(str(a.get("debit_amount", 0))) for a in adjustments)
    authority = _determine_authority(total)

    # Build reasoning chain
    logic_steps = _build_reasoning_steps(state)
    confidence = _compute_confidence(state)
    risk_assessment = _assess_risk(total, authority)

    reasoning_chain = ReasoningChain(
        trigger=state.get("inspection_request", {}),
        findings=state.get("inspection_report", {}),
        analysis=state.get("analysis_result", {}),
        logic_steps=logic_steps,
        confidence=confidence,
        risk_assessment=risk_assessment,
    )

    created_at = now_iso()
    sla_hours = AUTHORITY_SLA_HOURS.get(authority, 4.0)
    sla_deadline = _compute_sla_deadline(created_at, authority)

    proposal = AdjustmentProposal(
        proposal_id=new_id(),
        trace_id=trace_id,
        created_at=created_at,
        created_by=AgentId.FINANCIAL_ANALYST,
        journal_entries=[JournalEntry(**a) for a in adjustments],
        total_impact=TotalImpact(absolute=total, accounts_affected=len(adjustments)),
        required_approval=RequiredApproval(
            authority_level=authority,
            sla_hours=sla_hours,
        ),
        reasoning_chain=reasoning_chain,
        rejection_context=state.get("sign_off_reason") if attempts > 0 else None,
    )

    proposal_dict = proposal.model_dump()
    proposal_checksum = compute_proposal_checksum(proposal_dict)

    # Emit CREATED audit record
    created_record = create_audit_record(
        trace_id=trace_id,
        proposal_id=proposal_dict["proposal_id"],
        event_type=AuditEventType.CREATED,
        actor=AuditActor(type=ActorType.AGENT, id=AgentId.PROCESS_MANAGER),
        previous_records=previous_records,
        proposal_checksum=proposal_checksum,
        reasoning_snapshot=f"Proposal created with {len(adjustments)} adjustment(s), confidence={confidence:.2f}",
    )

    # Archive current proposal to history on rejection cycle
    proposal_history: list[dict] = []
    if attempts > 0:
        old_proposal = state.get("current_proposal")
        if old_proposal:
            proposal_history = [old_proposal]

    envelope = make_envelope(
        source_agent=AgentId.PROCESS_MANAGER,
        target_agent=AgentId.PROCESS_MANAGER,
        state_from=LedgerState.PROPOSAL,
        state_to=LedgerState.SIGN_OFF,
        payload=proposal_dict,
        trace_id=trace_id,
    )

    return {
        "current_state": LedgerState.PROPOSAL,
        "current_proposal": proposal_dict,
        "proposal_created_at": created_at,
        "sla_deadline": sla_deadline,
        "proposal_history": proposal_history,
        "audit_records": [created_record.model_dump()],
        "envelopes": [envelope],
    }


def sign_off_node(state: ReconciliationState) -> dict:
    """SIGN_OFF node: human review with SLA enforcement and full audit trail.

    In tests, decision is pre-set. On second attempt after rejection,
    auto-approves for deterministic termination of the cycle.
    SLA expiry auto-escalates.
    """
    trace_id = state.get("trace_id", "")
    attempts = state.get("sign_off_attempts", 0) + 1
    previous_records = state.get("audit_records", [])

    decision = state.get("sign_off_decision", SignOffDecision.APPROVE)
    authority = state.get("sign_off_authority", AuthorityLevel.L4_CONTROLLER)

    # Read sign-off metadata (testable via state injection)
    sign_off_timestamp = state.get("sign_off_timestamp") or now_iso()
    reviewer_notes = state.get("sign_off_reviewer_notes", "")
    actor_id = state.get("sign_off_actor_id", "HUMAN_REVIEWER")

    # SLA check: auto-escalate if sign-off is past deadline
    sla_deadline = state.get("sla_deadline", "")
    if sla_deadline and sign_off_timestamp > sla_deadline:
        decision = SignOffDecision.ESCALATE
        authority = AUTHORITY_ESCALATION.get(authority, AuthorityLevel.L4_CONTROLLER)

    # Auto-approve on second pass to break rejection cycle
    updates: dict = {}
    if decision == SignOffDecision.REJECT and attempts >= 2:
        decision = SignOffDecision.APPROVE
        updates["sign_off_decision"] = SignOffDecision.APPROVE
        updates["sign_off_authority"] = AuthorityLevel.L4_CONTROLLER
        authority = AuthorityLevel.L4_CONTROLLER

    # Compute time in review
    proposal_created_at = state.get("proposal_created_at", "")
    time_in_review_ms = 0
    if proposal_created_at:
        try:
            created_dt = datetime.fromisoformat(proposal_created_at)
            review_dt = datetime.fromisoformat(sign_off_timestamp)
            time_in_review_ms = int((review_dt - created_dt).total_seconds() * 1000)
        except (ValueError, TypeError):
            pass

    # Map decision to event type
    event_type_map = {
        SignOffDecision.APPROVE: AuditEventType.APPROVED,
        SignOffDecision.REJECT: AuditEventType.REJECTED,
        SignOffDecision.ESCALATE: AuditEventType.ESCALATED,
    }
    event_type = event_type_map[decision]

    # Compute proposal checksum
    proposal = state.get("current_proposal", {})
    proposal_checksum = compute_proposal_checksum(proposal) if proposal else ""

    # Rejection reason
    rejection_reason = state.get("sign_off_reason", "") if decision == SignOffDecision.REJECT else None

    # Emit audit record
    sign_off_record = create_audit_record(
        trace_id=trace_id,
        proposal_id=proposal.get("proposal_id", ""),
        event_type=event_type,
        actor=AuditActor(
            type=ActorType.HUMAN,
            id=actor_id,
            authority_level=authority,
        ),
        previous_records=previous_records,
        proposal_checksum=proposal_checksum,
        reasoning_snapshot=f"Sign-off decision: {decision}",
        reviewer_notes=reviewer_notes or None,
        rejection_reason=rejection_reason,
        time_in_review_ms=time_in_review_ms,
    )

    envelope = make_envelope(
        source_agent=AgentId.PROCESS_MANAGER,
        target_agent=AgentId.PROCESS_MANAGER,
        state_from=LedgerState.SIGN_OFF,
        state_to=LedgerState.COMMIT,
        payload={"decision": decision, "attempts": attempts},
        trace_id=trace_id,
    )

    return {
        "current_state": LedgerState.SIGN_OFF,
        "sign_off_attempts": attempts,
        "audit_records": [sign_off_record.model_dump()],
        "envelopes": [envelope],
        **updates,
    }


def commit_node(state: ReconciliationState) -> dict:
    """COMMIT node: stub reads commit_result from state."""
    trace_id = state.get("trace_id", "")
    result = state.get("commit_result", CommitResult.ACK)

    envelope = make_envelope(
        source_agent=AgentId.PROCESS_MANAGER,
        target_agent=AgentId.PROCESS_MANAGER,
        state_from=LedgerState.COMMIT,
        state_to=LedgerState.AUDIT_LOG if result == CommitResult.ACK else LedgerState.ERROR_QUARANTINE,
        payload={"commit_result": result},
        trace_id=trace_id,
    )

    return {
        "current_state": LedgerState.COMMIT,
        "envelopes": [envelope],
    }


def audit_log_node(state: ReconciliationState) -> dict:
    """AUDIT_LOG node: creates an immutable COMMITTED audit record using helpers."""
    trace_id = state.get("trace_id", "")
    previous_records = state.get("audit_records", [])
    proposal = state.get("current_proposal", {})
    proposal_checksum = compute_proposal_checksum(proposal) if proposal else ""

    record = create_audit_record(
        trace_id=trace_id,
        proposal_id=proposal.get("proposal_id", ""),
        event_type=AuditEventType.COMMITTED,
        actor=AuditActor(type=ActorType.AGENT, id=AgentId.PROCESS_MANAGER),
        previous_records=previous_records,
        proposal_checksum=proposal_checksum,
        reasoning_snapshot="Reconciliation complete",
    )

    envelope = make_envelope(
        source_agent=AgentId.PROCESS_MANAGER,
        target_agent=AgentId.SYSTEM,
        state_from=LedgerState.AUDIT_LOG,
        state_to=LedgerState.AUDIT_LOG,
        payload=record.model_dump(),
        trace_id=trace_id,
    )

    return {
        "current_state": LedgerState.AUDIT_LOG,
        "audit_records": [record.model_dump()],
        "envelopes": [envelope],
    }


def error_quarantine_node(state: ReconciliationState) -> dict:
    """ERROR_QUARANTINE node: isolate unresolvable issues."""
    trace_id = state.get("trace_id", "")

    envelope = make_envelope(
        source_agent=AgentId.PROCESS_MANAGER,
        target_agent=AgentId.SYSTEM,
        state_from=LedgerState.ERROR_QUARANTINE,
        state_to=LedgerState.ERROR_QUARANTINE,
        payload={"error_detail": state.get("error_detail", "Quarantined")},
        trace_id=trace_id,
    )

    return {
        "current_state": LedgerState.ERROR_QUARANTINE,
        "envelopes": [envelope],
    }


def self_heal_node(state: ReconciliationState) -> dict:
    """SELF_HEAL node: generate correction from known pattern."""
    trace_id = state.get("trace_id", "")
    report = state.get("inspection_report", {})
    findings = report.get("findings", [])

    # Find the self-healable finding
    correction = None
    for f in findings:
        if f.get("self_healable"):
            correction = {
                "pattern_id": f.get("pattern_id", ""),
                "finding_id": f.get("finding_id", ""),
                "debit_account": f.get("asset_id", "correction-debit"),
                "credit_account": "correction-offset",
                "amount": str(f.get("variance", 0)),
                "memo": f"Self-heal correction for pattern {f.get('pattern_id', '')}",
            }
            break

    if not correction:
        correction = {
            "pattern_id": "UNKNOWN",
            "amount": "0",
            "memo": "No self-healable finding found",
        }

    envelope = make_envelope(
        source_agent=AgentId.ASSET_WARDEN,
        target_agent=AgentId.FINANCIAL_ANALYST,
        state_from=LedgerState.SELF_HEAL,
        state_to=LedgerState.PROPOSAL,
        payload=correction,
        trace_id=trace_id,
    )

    return {
        "current_state": LedgerState.SELF_HEAL,
        "self_heal_correction": correction,
        "proposed_adjustments": [
            {
                "entry_id": new_id(),
                "debit_account": correction.get("debit_account", ""),
                "debit_amount": correction.get("amount", "0"),
                "credit_account": correction.get("credit_account", ""),
                "credit_amount": correction.get("amount", "0"),
                "memo": correction.get("memo", ""),
            }
        ],
        "envelopes": [envelope],
    }
