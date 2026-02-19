"""Guards for COMMIT state transitions."""

from sentient_ledger.models.enums import CommitResult
from sentient_ledger.models.graph_state import ReconciliationState


def mutation_succeeds(state: ReconciliationState) -> bool:
    return state.get("commit_result") == CommitResult.ACK


def mutation_fails(state: ReconciliationState) -> bool:
    return state.get("commit_result") == CommitResult.NACK
