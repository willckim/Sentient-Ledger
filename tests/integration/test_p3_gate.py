"""P3 Gate tests — D365 ingestion pipeline correctness."""

import os
import uuid

import pytest

from sentient_ledger.graph.builder import build_reconciliation_graph
from sentient_ledger.ingest.pipeline import (
    ingest_d365_export,
    ingest_fixed_assets,
    ingest_trial_balance,
)
from sentient_ledger.models.asset import CanonicalAssetRecord
from sentient_ledger.models.enums import LedgerState
from sentient_ledger.models.graph_state import create_initial_state
from sentient_ledger.models.trial_balance import CanonicalTrialBalance

FIXTURES = os.path.join(os.path.dirname(__file__), "..", "fixtures", "d365")


@pytest.fixture
def graph():
    return build_reconciliation_graph()


def _base_state(**overrides):
    state = create_initial_state(str(uuid.uuid4()))
    state.update(overrides)
    return state


class TestP3GateTrialBalanceExport:
    """Gate: Clean TB CSV → 5 rows, 0 malformed, validates as CanonicalTrialBalance, graph → AUDIT_LOG."""

    def test_p3_gate_trial_balance_export(self, graph):
        result = ingest_trial_balance(
            file_path=os.path.join(FIXTURES, "trial_balance_clean.csv"),
            ingestion_id="GATE-TB-001",
        )

        # 5 rows, 0 malformed
        assert result.total_rows == 5
        assert result.malformed_rows == 0
        assert len(result.trial_balance_records) == 5

        # All validate as CanonicalTrialBalance
        for rec in result.trial_balance_records:
            tb = CanonicalTrialBalance(**rec)
            assert tb.record_id
            assert tb.source == "DYNAMICS_365"
            assert tb.ingestion_id == "GATE-TB-001"
            assert tb.integrity.source_row_hash

        # Graph reaches AUDIT_LOG
        state = _base_state()
        state.update(result.to_state_dict())
        graph_result = graph.invoke(state)
        assert graph_result["current_state"] == LedgerState.AUDIT_LOG


class TestP3GateFixedAssetExport:
    """Gate: Clean FA CSV → 3 rows, 0 malformed, enum translations correct."""

    def test_p3_gate_fixed_asset_export(self):
        result = ingest_fixed_assets(
            file_path=os.path.join(FIXTURES, "fixed_assets_clean.csv"),
            ingestion_id="GATE-FA-001",
        )

        # 3 rows, 0 malformed
        assert result.total_rows == 3
        assert result.malformed_rows == 0
        assert len(result.asset_register) == 3

        # All validate as CanonicalAssetRecord
        for rec in result.asset_register:
            fa = CanonicalAssetRecord(**rec)
            assert fa.record_id
            assert fa.source == "DYNAMICS_365"

        # Enum translations correct
        methods = [r["acquisition"]["method"] for r in result.asset_register]
        assert "STRAIGHT_LINE" in methods
        assert "DOUBLE_DECLINING" in methods

        conventions = [r["acquisition"]["convention"] for r in result.asset_register]
        assert "HALF_MONTH" in conventions
        assert "FULL_MONTH" in conventions
        assert "HALF_YEAR" in conventions

        statuses = [r["current_state"]["status"] for r in result.asset_register]
        assert all(s == "ACTIVE" for s in statuses)


class TestP3GateCombinedExportWithErrors:
    """Gate: Mixed CSV — correct total_rows, malformed identified, clean rows ingested."""

    def test_p3_gate_combined_export_with_errors(self):
        result = ingest_d365_export(
            tb_content=open(os.path.join(FIXTURES, "mixed_with_errors.csv")).read(),
            fa_content=open(os.path.join(FIXTURES, "fixed_assets_clean.csv")).read(),
            ingestion_id="GATE-MIX-001",
        )

        # Total rows = TB (5) + FA (3) = 8
        assert result.total_rows == 8

        # TB has 3 malformed (empty account, negative debits, XYZ currency)
        # FA has 0 malformed
        assert result.malformed_rows == 3

        # Clean TB rows still ingested (2 out of 5)
        assert len(result.trial_balance_records) == 2

        # All FA rows ingested (3 out of 3)
        assert len(result.asset_register) == 3

        # malformed_pct computed correctly
        expected_pct = 3 / 8 * 100.0
        assert result.malformed_pct == pytest.approx(expected_pct)
