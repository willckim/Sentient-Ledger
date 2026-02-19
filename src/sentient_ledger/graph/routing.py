"""Routing functions for conditional edges in the reconciliation graph.

Each function composes guard conditions and returns the target node name.
"""

from sentient_ledger.guards.analysis_guards import adjustments_identified, clean_analysis
from sentient_ledger.guards.asset_guards import inspection_complete, known_error_pattern_matched
from sentient_ledger.guards.commit_guards import mutation_fails, mutation_succeeds
from sentient_ledger.guards.compliance_guards import asset_discrepancy_detected, no_asset_discrepancies
from sentient_ledger.guards.ingest_guards import malformed_exceeds_threshold, schema_validation_passes
from sentient_ledger.guards.signoff_guards import human_approves, human_escalates, human_rejects
from sentient_ledger.models.graph_state import ReconciliationState


def route_after_ingest(state: ReconciliationState) -> str:
    """INGEST → COMPLIANCE_SCAN or ERROR_QUARANTINE."""
    if malformed_exceeds_threshold(state):
        return "error_quarantine"
    return "compliance_scan"


def route_after_compliance(state: ReconciliationState) -> str:
    """COMPLIANCE_SCAN → ASSET_INSPECTION or ANALYSIS."""
    if asset_discrepancy_detected(state):
        return "asset_inspection"
    return "analysis"


def route_after_asset_inspection(state: ReconciliationState) -> str:
    """ASSET_INSPECTION → SELF_HEAL or ANALYSIS."""
    if known_error_pattern_matched(state):
        return "self_heal"
    return "analysis"


def route_after_analysis(state: ReconciliationState) -> str:
    """ANALYSIS → PROPOSAL or AUDIT_LOG."""
    if adjustments_identified(state):
        return "proposal"
    return "audit_log"


def route_after_sign_off(state: ReconciliationState) -> str:
    """SIGN_OFF → COMMIT, PROPOSAL, or ERROR_QUARANTINE."""
    if human_approves(state):
        return "commit"
    if human_rejects(state):
        return "proposal"
    if human_escalates(state):
        return "error_quarantine"
    # Default: escalate if no valid decision
    return "error_quarantine"


def route_after_commit(state: ReconciliationState) -> str:
    """COMMIT → AUDIT_LOG or ERROR_QUARANTINE."""
    if mutation_succeeds(state):
        return "audit_log"
    return "error_quarantine"
