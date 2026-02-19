"""Guards for COMPLIANCE_SCAN state transitions."""

from sentient_ledger.models.graph_state import ReconciliationState


def asset_discrepancy_detected(state: ReconciliationState) -> bool:
    return len(state.get("asset_flags", [])) > 0


def no_asset_discrepancies(state: ReconciliationState) -> bool:
    return len(state.get("asset_flags", [])) == 0
