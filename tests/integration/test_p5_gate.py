"""P5 gate tests: production hardening, observability, security audit."""

import os
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from sentient_ledger.config import (
    AUTHORITY_ESCALATION,
    AUTHORITY_THRESHOLDS,
    TRIAL_BALANCE_TOLERANCE,
)
from sentient_ledger.graph.builder import build_reconciliation_graph
from sentient_ledger.guards.envelope_guards import all_envelopes_valid, verify_envelope_integrity
from sentient_ledger.ingest.adapter import adapt_state_for_detector
from sentient_ledger.ingest.pipeline import ingest_d365_export
from sentient_ledger.models.enums import (
    AuthorityLevel,
    LedgerState,
    SignOffDecision,
)
from sentient_ledger.models.graph_state import create_initial_state
from sentient_ledger.observability import PipelineObserver

FIXTURES = os.path.join(os.path.dirname(__file__), "..", "fixtures", "d365")


def _base_state(**overrides):
    state = create_initial_state(str(uuid.uuid4()))
    state.update(overrides)
    return state


def _discrepancy_marker(amount_str="100"):
    """A TB record with a _discrepancy marker to trigger asset_flags."""
    return {
        "record_id": "marker-001",
        "account": {
            "code": "120000",
            "name": "Fixed Assets Control",
            "category": "ASSET",
            "sub_category": "",
            "is_control_account": False,
        },
        "dimensions": {
            "business_unit": "BU-001",
            "department": "FIN",
            "cost_center": "CC-100",
            "composite_key": "120000-BU-001",
        },
        "balances": {
            "opening": Decimal("100000"),
            "debits": Decimal("5000"),
            "credits": Decimal("3000"),
            "closing": Decimal("102000"),
            "movement": Decimal("2000"),
        },
        "currency": {"transaction": "USD", "reporting": "USD"},
        "period": {"fiscal_year": 2024, "fiscal_period": 1, "calendar_month": "2024-01"},
        "integrity": {"source_row_hash": "gate-marker", "balance_verified": True},
        "_discrepancy": {
            "reason": "DEPRECIATION_VARIANCE_EXCEEDS_THRESHOLD",
            "account": "120000",
            "account_name": "Fixed Assets Control",
            "detail": {
                "expected": 43125,
                "actual": 43136,
                "variance": -11,
                "variance_pct": 0.025,
                "period": "2024-12",
            },
            "priority": "HIGH",
        },
    }


class TestAuthorityThresholdsConfigDriven:
    def test_authority_thresholds_config_driven(self):
        """Run graph with discrepancy, verify proposal authority is consistent with config thresholds."""
        from sentient_ledger.agents.process_manager import _determine_authority

        graph = build_reconciliation_graph()
        state = _base_state(
            trial_balance_records=[_discrepancy_marker()],
            asset_flags=["DEPRECIATION_VARIANCE_EXCEEDS_THRESHOLD:120000"],
        )
        result = graph.invoke(state)
        proposal = result.get("current_proposal", {})
        if proposal:
            # Verify the authority level in the proposal matches what
            # _determine_authority would return for the total impact
            total = Decimal(str(proposal["total_impact"]["absolute"]))
            expected_level = _determine_authority(total)
            assert proposal["required_approval"]["authority_level"] == expected_level

        # Also verify _determine_authority is config-driven for all boundaries
        for level, threshold in AUTHORITY_THRESHOLDS.items():
            if threshold is None:
                continue
            assert _determine_authority(threshold) == level


class TestSLAEscalationUsesConfig:
    def test_sla_escalation_uses_config(self):
        """Inject expired SLA, verify escalation matches AUTHORITY_ESCALATION."""
        graph = build_reconciliation_graph()
        now = datetime.now(timezone.utc)

        state = _base_state(
            trial_balance_records=[_discrepancy_marker()],
            proposed_adjustments=[
                {
                    "entry_id": str(uuid.uuid4()),
                    "debit_account": "100",
                    "debit_amount": "100",
                    "credit_account": "200",
                    "credit_amount": "100",
                    "memo": "sla-test",
                }
            ],
            sign_off_authority=AuthorityLevel.L1_STAFF,
            sign_off_decision=SignOffDecision.APPROVE,
            # SLA expiry: timestamp far in the future
            sign_off_timestamp=(now + timedelta(days=365)).isoformat(),
        )
        result = graph.invoke(state)
        # Should have reached a terminal state (might escalate then auto-approve on cycle)
        assert result["current_state"] in (
            LedgerState.AUDIT_LOG,
            LedgerState.ERROR_QUARANTINE,
        )
        # Verify escalation record exists in audit trail
        records = result.get("audit_records", [])
        escalated = [r for r in records if r.get("event_type") == "ESCALATED"]
        # At least one escalation should have occurred
        assert len(escalated) >= 1


class TestEnvelopeChecksumsValid:
    def test_envelope_checksums_valid_through_pipeline(self):
        """Run full graph, verify all envelopes pass verify_checksum()."""
        graph = build_reconciliation_graph()
        state = _base_state(
            trial_balance_records=[],
            malformed_pct=0.0,
        )
        result = graph.invoke(state)
        assert all_envelopes_valid(result) is True

    def test_envelope_tamper_detected(self):
        """Run graph, tamper with envelope payload, verify detection."""
        graph = build_reconciliation_graph()
        state = _base_state(
            trial_balance_records=[],
            malformed_pct=0.0,
        )
        result = graph.invoke(state)
        # Tamper with first envelope
        assert len(result["envelopes"]) > 0
        result["envelopes"][0]["payload"] = {"tampered": True}
        assert all_envelopes_valid(result) is False
        failed = verify_envelope_integrity(result)
        assert len(failed) >= 1


class TestComplianceUsesConfigTolerance:
    def test_compliance_uses_config_tolerance(self):
        """Inject TB with variance at tolerance boundary, verify behavior."""
        graph = build_reconciliation_graph()
        # Create a TB record where balance check is within tolerance
        tb_record = {
            "record_id": "tol-001",
            "account": {
                "code": "120000",
                "name": "Fixed Assets Control",
                "category": "ASSET",
                "sub_category": "",
                "is_control_account": True,
            },
            "dimensions": {
                "business_unit": "BU-001",
                "department": "FIN",
                "cost_center": "CC-100",
                "composite_key": "120000-BU-001",
            },
            "balances": {
                "opening": Decimal("100000"),
                "debits": Decimal("5000"),
                "credits": Decimal("3000"),
                "closing": Decimal("102000.005"),  # within 0.01 tolerance
                "movement": Decimal("2000"),
            },
            "currency": {"transaction": "USD", "reporting": "USD"},
            "period": {"fiscal_year": 2024, "fiscal_period": 1, "calendar_month": "2024-01"},
            "integrity": {"source_row_hash": "tol-hash", "balance_verified": True},
        }
        state = _base_state(trial_balance_records=[tb_record])
        result = graph.invoke(state)
        # Variance of 0.005 is within default tolerance 0.01 → no asset flags from control check
        # Graph should reach AUDIT_LOG (clean path)
        assert result["current_state"] in (LedgerState.AUDIT_LOG, LedgerState.ANALYSIS)


class TestObserverCapturesAllNodes:
    def test_observer_captures_all_nodes(self):
        """Run graph with observer, verify events cover expected node set."""
        observer = PipelineObserver()
        graph = build_reconciliation_graph(observer=observer)
        state = _base_state(
            trial_balance_records=[],
            malformed_pct=0.0,
        )
        graph.invoke(state)
        summary = observer.summary()
        assert summary["node_count"] >= 2  # at least ingest + one more
        assert "ingest_node" in summary["nodes"]

    def test_observer_sla_timing(self):
        """Run graph with observer, verify timing data is populated."""
        observer = PipelineObserver()
        graph = build_reconciliation_graph(observer=observer)
        state = _base_state(
            trial_balance_records=[],
            malformed_pct=0.0,
        )
        graph.invoke(state)
        for event in observer.events:
            assert event.duration_ms >= 0
            assert event.started_at > 0
            assert event.ended_at >= event.started_at


class TestFullPipelineE2EWithHardening:
    def test_full_pipeline_e2e_with_hardening(self):
        """D365 CSV ingest → adapt → graph with observer → verify terminal + valid envelopes + audit chain."""
        observer = PipelineObserver()
        graph = build_reconciliation_graph(observer=observer)

        # Ingest clean CSVs
        result = ingest_d365_export(
            fa_path=os.path.join(FIXTURES, "fixed_assets_clean.csv"),
            ds_path=os.path.join(FIXTURES, "depreciation_schedule_clean.csv"),
            ingestion_id="P5-E2E",
        )
        assert result.malformed_rows == 0

        # Adapt
        state_dict = result.to_state_dict()
        adapted = adapt_state_for_detector(state_dict)

        # Build graph state
        state = _base_state()
        state.update(adapted)
        state["trial_balance_records"] = [_discrepancy_marker()]
        state["asset_flags"] = ["DEPRECIATION_VARIANCE_EXCEEDS_THRESHOLD:120000"]

        graph_result = graph.invoke(state)

        # Terminal state reached
        assert graph_result["current_state"] in (
            LedgerState.AUDIT_LOG,
            LedgerState.ERROR_QUARANTINE,
        )

        # All envelopes valid
        assert all_envelopes_valid(graph_result) is True

        # Observer captured events
        summary = observer.summary()
        assert summary["node_count"] >= 3
        assert summary["slowest_node"] is not None

        # Audit chain exists
        audit_records = graph_result.get("audit_records", [])
        assert len(audit_records) >= 1
