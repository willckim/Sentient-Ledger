"""Build the reconciliation state graph."""

from __future__ import annotations

from langgraph.graph import END, StateGraph

from sentient_ledger.agents.asset_warden import asset_warden_node
from sentient_ledger.agents.compliance_specialist import compliance_specialist_node
from sentient_ledger.agents.financial_analyst import financial_analyst_node
from sentient_ledger.agents.process_manager import (
    audit_log_node,
    commit_node,
    error_quarantine_node,
    ingest_node,
    proposal_node,
    self_heal_node,
    sign_off_node,
)
from sentient_ledger.graph.routing import (
    route_after_analysis,
    route_after_asset_inspection,
    route_after_commit,
    route_after_compliance,
    route_after_ingest,
    route_after_sign_off,
)
from sentient_ledger.models.graph_state import ReconciliationState
from sentient_ledger.observability import PipelineObserver, wrap_node


def build_reconciliation_graph(
    observer: PipelineObserver | None = None,
) -> StateGraph:
    """Construct and compile the reconciliation state graph.

    Args:
        observer: Optional PipelineObserver to capture node timing events.

    Returns a compiled StateGraph with all nodes and edges wired.
    """
    graph = StateGraph(ReconciliationState)

    def _node(fn):
        return wrap_node(fn, observer) if observer else fn

    # Add nodes
    graph.add_node("ingest", _node(ingest_node))
    graph.add_node("compliance_scan", _node(compliance_specialist_node))
    graph.add_node("asset_inspection", _node(asset_warden_node))
    graph.add_node("analysis", _node(financial_analyst_node))
    graph.add_node("proposal", _node(proposal_node))
    graph.add_node("sign_off", _node(sign_off_node))
    graph.add_node("commit", _node(commit_node))
    graph.add_node("audit_log", _node(audit_log_node))
    graph.add_node("error_quarantine", _node(error_quarantine_node))
    graph.add_node("self_heal", _node(self_heal_node))

    # Set entry point
    graph.set_entry_point("ingest")

    # Conditional edges
    graph.add_conditional_edges("ingest", route_after_ingest, {
        "compliance_scan": "compliance_scan",
        "error_quarantine": "error_quarantine",
    })

    graph.add_conditional_edges("compliance_scan", route_after_compliance, {
        "asset_inspection": "asset_inspection",
        "analysis": "analysis",
    })

    graph.add_conditional_edges("asset_inspection", route_after_asset_inspection, {
        "self_heal": "self_heal",
        "analysis": "analysis",
    })

    # SELF_HEAL always goes to PROPOSAL
    graph.add_edge("self_heal", "proposal")

    graph.add_conditional_edges("analysis", route_after_analysis, {
        "proposal": "proposal",
        "audit_log": "audit_log",
    })

    # PROPOSAL always goes to SIGN_OFF
    graph.add_edge("proposal", "sign_off")

    graph.add_conditional_edges("sign_off", route_after_sign_off, {
        "commit": "commit",
        "proposal": "proposal",
        "error_quarantine": "error_quarantine",
    })

    graph.add_conditional_edges("commit", route_after_commit, {
        "audit_log": "audit_log",
        "error_quarantine": "error_quarantine",
    })

    # Terminal nodes
    graph.add_edge("audit_log", END)
    graph.add_edge("error_quarantine", END)

    return graph.compile()
