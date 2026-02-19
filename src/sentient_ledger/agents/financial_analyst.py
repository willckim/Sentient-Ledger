"""Financial Analyst agent stub.

Deterministic: examines findings and trial balance data,
produces adjustment proposals if anomalies are found.
"""

from decimal import Decimal

from sentient_ledger.agents.base import make_envelope, new_id, now_iso
from sentient_ledger.models.enums import (
    AgentId,
    AuthorityLevel,
    LedgerState,
)
from sentient_ledger.models.graph_state import ReconciliationState
from sentient_ledger.models.proposal import (
    AdjustmentProposal,
    JournalEntry,
    ReasoningStep,
    RequiredApproval,
    TotalImpact,
)


def financial_analyst_node(state: ReconciliationState) -> dict:
    """Analyze findings and trial balance data.

    Stub: if inspection findings exist with a nonzero variance,
    or if explicit adjustments are passed, generate a proposal.
    Otherwise produce a clean analysis.
    """
    trace_id = state.get("trace_id", "")
    report = state.get("inspection_report", {})
    findings = report.get("findings", [])

    # Check for self-heal correction that fed into analysis
    self_heal = state.get("self_heal_correction")

    adjustments: list[dict] = []

    # Generate adjustments from findings
    for finding in findings:
        variance = Decimal(str(finding.get("variance", 0)))
        if variance > 0:
            entry = JournalEntry(
                entry_id=new_id(),
                debit_account=finding.get("asset_id", "UNKNOWN"),
                debit_amount=variance,
                credit_account="adjustment-offset",
                credit_amount=variance,
                memo=f"Adjustment for {finding.get('error_type', 'unknown')}",
            )
            adjustments.append(entry.model_dump())

    # If self-heal correction exists, create adjustment from it
    if self_heal and not adjustments:
        correction = self_heal
        entry = JournalEntry(
            entry_id=new_id(),
            debit_account=correction.get("debit_account", "correction-debit"),
            debit_amount=Decimal(str(correction.get("amount", 0))),
            credit_account=correction.get("credit_account", "correction-credit"),
            credit_amount=Decimal(str(correction.get("amount", 0))),
            memo=correction.get("memo", "Self-heal correction"),
        )
        adjustments.append(entry.model_dump())

    # Check for explicit adjustments marker
    explicit = state.get("_force_adjustments")
    if explicit:
        adjustments = explicit

    envelope = make_envelope(
        source_agent=AgentId.FINANCIAL_ANALYST,
        target_agent=AgentId.PROCESS_MANAGER,
        state_from=LedgerState.ANALYSIS,
        state_to=LedgerState.PROPOSAL if adjustments else LedgerState.AUDIT_LOG,
        payload={"adjustments": adjustments, "findings_count": len(findings)},
        trace_id=trace_id,
    )

    return {
        "current_state": LedgerState.ANALYSIS,
        "proposed_adjustments": adjustments,
        "analysis_result": {"findings_reviewed": len(findings), "adjustments": len(adjustments)},
        "envelopes": [envelope],
    }
