"""Guards for ANALYSIS state transitions."""

from sentient_ledger.models.graph_state import ReconciliationState


def adjustments_identified(state: ReconciliationState) -> bool:
    return len(state.get("proposed_adjustments", [])) > 0


def clean_analysis(state: ReconciliationState) -> bool:
    return len(state.get("proposed_adjustments", [])) == 0
