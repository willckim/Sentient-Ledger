"""Guards for SELF_HEAL state transitions."""

from sentient_ledger.models.graph_state import ReconciliationState


def correction_generated(state: ReconciliationState) -> bool:
    return state.get("self_heal_correction") is not None
