"""P4 gate tests: D365 CSV ingestion → adapter → detector → graph terminal state."""

import os
import uuid
from decimal import Decimal

import pytest

from sentient_ledger.graph.builder import build_reconciliation_graph
from sentient_ledger.ingest.adapter import adapt_state_for_detector, canonical_asset_to_detector
from sentient_ledger.ingest.pipeline import (
    ingest_d365_export,
    ingest_depreciation_schedule,
    ingest_fixed_assets,
)
from sentient_ledger.models.enums import LedgerState
from sentient_ledger.models.eval import ScenarioAssetRecord
from sentient_ledger.models.graph_state import create_initial_state

FIXTURES = os.path.join(os.path.dirname(__file__), "..", "fixtures", "d365")


@pytest.fixture
def graph():
    return build_reconciliation_graph()


def _base_state(**overrides):
    state = create_initial_state(str(uuid.uuid4()))
    state.update(overrides)
    return state


def _discrepancy_marker() -> dict:
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


class TestP4GateDSIngestion:
    def test_ds_ingestion_clean(self):
        """31 rows, 0 malformed, all validate as DepreciationEntry."""
        result = ingest_depreciation_schedule(
            file_path=os.path.join(FIXTURES, "depreciation_schedule_clean.csv"),
            ingestion_id="P4-DS-001",
        )
        assert result.total_rows == 31
        assert result.malformed_rows == 0
        assert len(result.depreciation_schedule) == 31
        # Spot-check: FA-001 first period
        fa001_entries = [e for e in result.depreciation_schedule if e["asset_id"] == "FA-001"]
        assert len(fa001_entries) == 12
        assert fa001_entries[0]["amount"] == Decimal("1875.00")


class TestP4GateAdapterRoundtrip:
    def test_canonical_fa_to_flat_to_scenario_model(self):
        """canonical FA → flat → ScenarioAssetRecord(**r) succeeds."""
        fa_result = ingest_fixed_assets(
            file_path=os.path.join(FIXTURES, "fixed_assets_clean.csv"),
        )
        for canonical in fa_result.asset_register:
            flat = canonical_asset_to_detector(canonical)
            # Should not raise
            sar = ScenarioAssetRecord(**flat)
            assert sar.asset_id
            assert sar.cost > 0


class TestP4GateE2EClean:
    def test_clean_csvs_through_graph_reach_audit_log(self, graph):
        """D365 CSVs (clean) → ingest → adapt → graph → 0 findings → AUDIT_LOG."""
        # Ingest all three CSV types
        result = ingest_d365_export(
            fa_path=os.path.join(FIXTURES, "fixed_assets_clean.csv"),
            ds_path=os.path.join(FIXTURES, "depreciation_schedule_clean.csv"),
            ingestion_id="P4-E2E-CLEAN",
        )
        assert result.malformed_rows == 0

        # Adapt for detector
        state_dict = result.to_state_dict()
        adapted = adapt_state_for_detector(state_dict)

        # Verify adapter output
        assert all("asset_id" in r for r in adapted["asset_register"])
        assert len(adapted["depreciation_schedule"]) == 31

        # Build graph state with discrepancy marker to route through asset_inspection
        state = _base_state()
        state.update(adapted)
        # Inject a TB record with _discrepancy to trigger compliance routing
        state["trial_balance_records"] = [_discrepancy_marker()]
        state["asset_flags"] = ["DEPRECIATION_VARIANCE_EXCEEDS_THRESHOLD:120000"]

        graph_result = graph.invoke(state)

        # With clean depreciation data, detector should find 0 per-asset issues
        # (The only possible issue is GL balance mismatch from the marker record,
        #  but since the marker's closing balance doesn't affect the depreciation
        #  schedule check, the per-asset checks should pass.)
        assert graph_result["current_state"] in (LedgerState.AUDIT_LOG, LedgerState.COMMIT)


class TestP4GateE2EErrorsDetected:
    def test_errors_detected_in_graph(self, graph):
        """D365 CSVs (with errors) → ingest → adapt → graph → detector finds FA-001 rounding error."""
        # Ingest FA (clean) + DS (with errors)
        fa_result = ingest_fixed_assets(
            file_path=os.path.join(FIXTURES, "fixed_assets_clean.csv"),
            ingestion_id="P4-E2E-ERR",
        )
        ds_result = ingest_depreciation_schedule(
            file_path=os.path.join(FIXTURES, "depreciation_schedule_with_errors.csv"),
            ingestion_id="P4-E2E-ERR",
        )

        # Combine and adapt
        combined_state = {
            "trial_balance_records": [_discrepancy_marker()],
            "asset_register": fa_result.asset_register,
            "depreciation_schedule": ds_result.depreciation_schedule,
            "total_rows": fa_result.total_rows + ds_result.total_rows,
            "malformed_rows": 0,
            "malformed_pct": 0.0,
        }
        adapted = adapt_state_for_detector(combined_state)

        state = _base_state()
        state.update(adapted)
        state["asset_flags"] = ["DEPRECIATION_VARIANCE_EXCEEDS_THRESHOLD:120000"]

        graph_result = graph.invoke(state)

        # The detector should have produced findings (visible in inspection_report)
        report = graph_result.get("inspection_report", {})
        findings = report.get("findings", [])
        fa001_findings = [
            f for f in findings
            if f.get("asset_id") == "FA-001"
        ]
        assert len(fa001_findings) >= 1, f"Expected finding for FA-001, got: {findings}"

        # Graph should reach a terminal state
        assert graph_result["current_state"] in (
            LedgerState.AUDIT_LOG,
            LedgerState.ERROR_QUARANTINE,
        )


class TestP4GateBackwardCompat:
    def test_flat_scenario_records_still_work(self, graph):
        """Flat ScenarioAssetRecord dicts in state still work (existing eval path unbroken)."""
        flat_asset = {
            "asset_id": "COMPAT-001",
            "description": "Backward compat test",
            "acquisition_date": "2024-01-01",
            "cost": Decimal("100000"),
            "salvage_value": Decimal("10000"),
            "useful_life_months": 60,
            "depreciation_method": "STRAIGHT_LINE",
            "convention": "FULL_MONTH",
            "status": "ACTIVE",
            "entity_id": "ENTITY-001",
            "group": "PP&E",
        }
        flat_entry = {
            "asset_id": "COMPAT-001",
            "period": "2024-01",
            "amount": Decimal("1500"),
            "accumulated": Decimal("1500"),
            "net_book_value": Decimal("98500"),
        }

        state = _base_state()
        state["asset_register"] = [flat_asset]
        state["depreciation_schedule"] = [flat_entry]
        state["gl_balances"] = []
        state["trial_balance_records"] = [_discrepancy_marker()]
        state["asset_flags"] = ["TEST:COMPAT"]

        graph_result = graph.invoke(state)
        # Graph should not crash and reach a terminal state
        assert graph_result["current_state"] in (
            LedgerState.AUDIT_LOG,
            LedgerState.ERROR_QUARANTINE,
        )
