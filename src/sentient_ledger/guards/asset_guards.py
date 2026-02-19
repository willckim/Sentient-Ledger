"""Guards for ASSET_INSPECTION state transitions."""

from sentient_ledger.config import SELF_HEAL_CONFIDENCE_THRESHOLD
from sentient_ledger.models.graph_state import ReconciliationState


def known_error_pattern_matched(state: ReconciliationState) -> bool:
    report = state.get("inspection_report", {})
    findings = report.get("findings", [])
    for f in findings:
        if f.get("self_healable") and f.get("confidence", 0) >= SELF_HEAL_CONFIDENCE_THRESHOLD:
            return True
    return False


def inspection_complete(state: ReconciliationState) -> bool:
    return not known_error_pattern_matched(state)
