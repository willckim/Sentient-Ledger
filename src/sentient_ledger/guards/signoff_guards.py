"""Guards for SIGN_OFF state transitions."""

from sentient_ledger.models.enums import AUTHORITY_RANK, AuthorityLevel, SignOffDecision
from sentient_ledger.models.graph_state import ReconciliationState


def human_approves(state: ReconciliationState) -> bool:
    if state.get("sign_off_decision") != SignOffDecision.APPROVE:
        return False
    # Check authority level is sufficient
    signer = state.get("sign_off_authority", AuthorityLevel.L1_STAFF)
    proposal = state.get("current_proposal", {})
    required = proposal.get("required_approval", {}).get(
        "authority_level", AuthorityLevel.L1_STAFF
    )
    return AUTHORITY_RANK.get(signer, 0) >= AUTHORITY_RANK.get(required, 0)


def human_rejects(state: ReconciliationState) -> bool:
    return state.get("sign_off_decision") == SignOffDecision.REJECT


def human_escalates(state: ReconciliationState) -> bool:
    return state.get("sign_off_decision") == SignOffDecision.ESCALATE
