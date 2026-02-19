"""Guards for the INGEST state transitions."""

from sentient_ledger.config import MALFORMED_ROW_THRESHOLD_PCT
from sentient_ledger.models.graph_state import ReconciliationState


def schema_validation_passes(state: ReconciliationState) -> bool:
    return state.get("malformed_pct", 0.0) <= MALFORMED_ROW_THRESHOLD_PCT


def malformed_exceeds_threshold(state: ReconciliationState) -> bool:
    return state.get("malformed_pct", 0.0) > MALFORMED_ROW_THRESHOLD_PCT
