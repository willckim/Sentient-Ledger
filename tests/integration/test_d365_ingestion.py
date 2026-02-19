"""Integration tests for D365 ingestion pipeline through graph."""

import os
import uuid

import pytest

from sentient_ledger.graph.builder import build_reconciliation_graph
from sentient_ledger.ingest.pipeline import ingest_fixed_assets, ingest_trial_balance
from sentient_ledger.models.enums import LedgerState
from sentient_ledger.models.graph_state import create_initial_state
from sentient_ledger.models.trial_balance import CanonicalTrialBalance
from sentient_ledger.models.asset import CanonicalAssetRecord

FIXTURES = os.path.join(os.path.dirname(__file__), "..", "fixtures", "d365")


@pytest.fixture
def graph():
    return build_reconciliation_graph()


def _base_state(**overrides):
    state = create_initial_state(str(uuid.uuid4()))
    state.update(overrides)
    return state


class TestCleanTBThroughGraph:
    def test_clean_tb_through_graph_reaches_audit_log(self, graph):
        """Ingest clean TB CSV → inject into state → graph reaches AUDIT_LOG."""
        result = ingest_trial_balance(
            file_path=os.path.join(FIXTURES, "trial_balance_clean.csv"),
            ingestion_id="INT-TB-001",
        )
        assert result.malformed_rows == 0

        state = _base_state()
        state_update = result.to_state_dict()
        state.update(state_update)

        graph_result = graph.invoke(state)
        assert graph_result["current_state"] == LedgerState.AUDIT_LOG


class TestCleanFAPopulatesAssetRegister:
    def test_clean_fa_populates_asset_register(self, graph):
        """Ingest clean FA CSV → asset_register populated in state."""
        result = ingest_fixed_assets(
            file_path=os.path.join(FIXTURES, "fixed_assets_clean.csv"),
            ingestion_id="INT-FA-001",
        )
        assert result.malformed_rows == 0
        assert len(result.asset_register) == 3

        state = _base_state()
        state_update = result.to_state_dict()
        state.update(state_update)

        # asset_register should be populated
        assert len(state["asset_register"]) == 3
        assert state["asset_register"][0]["identity"]["asset_id"] == "FA-001"


class TestErrorCSVQuarantine:
    def test_error_csv_quarantines_when_threshold_exceeded(self, graph):
        """Mixed CSV with >1% malformed → graph quarantines."""
        result = ingest_trial_balance(
            file_path=os.path.join(FIXTURES, "mixed_with_errors.csv"),
        )
        assert result.malformed_pct > 1.0  # 60% malformed

        state = _base_state()
        state_update = result.to_state_dict()
        state.update(state_update)

        graph_result = graph.invoke(state)
        assert graph_result["current_state"] == LedgerState.ERROR_QUARANTINE


class TestPipelineStateBackwardCompat:
    def test_pipeline_state_backward_compatible(self, graph):
        """Pipeline-generated state is compatible with hand-built state dicts."""
        result = ingest_trial_balance(
            file_path=os.path.join(FIXTURES, "trial_balance_clean.csv"),
        )
        state_dict = result.to_state_dict()

        # All keys expected by graph state
        assert "trial_balance_records" in state_dict
        assert "asset_register" in state_dict
        assert "depreciation_schedule" in state_dict
        assert "total_rows" in state_dict
        assert "malformed_rows" in state_dict
        assert "malformed_pct" in state_dict

        # Types match graph expectations
        assert isinstance(state_dict["trial_balance_records"], list)
        assert isinstance(state_dict["total_rows"], int)
        assert isinstance(state_dict["malformed_pct"], float)


class TestIngestedRecordsMatchCanonicalModel:
    def test_ingested_records_match_canonical_model(self):
        """Ingested TB records can be validated against CanonicalTrialBalance."""
        result = ingest_trial_balance(
            file_path=os.path.join(FIXTURES, "trial_balance_clean.csv"),
        )
        for rec in result.trial_balance_records:
            # Should not raise
            tb = CanonicalTrialBalance(**rec)
            assert tb.record_id
            assert tb.account.code
            assert tb.integrity.source_row_hash

    def test_ingested_fa_records_match_canonical_model(self):
        """Ingested FA records can be validated against CanonicalAssetRecord."""
        result = ingest_fixed_assets(
            file_path=os.path.join(FIXTURES, "fixed_assets_clean.csv"),
        )
        for rec in result.asset_register:
            fa = CanonicalAssetRecord(**rec)
            assert fa.record_id
            assert fa.identity.asset_id
            assert fa.integrity.source_row_hash
