"""Unit tests for compliance specialist config wiring."""

import uuid
from decimal import Decimal
from unittest.mock import patch

from sentient_ledger.agents.compliance_specialist import compliance_specialist_node
from sentient_ledger.models.graph_state import create_initial_state


def _base_state(**overrides):
    state = create_initial_state(str(uuid.uuid4()))
    state.update(overrides)
    return state


def _make_tb_record(opening, debits, credits, closing, *, is_control=True, code="120000"):
    return {
        "record_id": f"rec-{code}",
        "account": {
            "code": code,
            "name": "Test Account",
            "category": "ASSET",
            "sub_category": "",
            "is_control_account": is_control,
        },
        "dimensions": {
            "business_unit": "BU-001",
            "department": "FIN",
            "cost_center": "CC-100",
            "composite_key": f"{code}-BU-001",
        },
        "balances": {
            "opening": Decimal(str(opening)),
            "debits": Decimal(str(debits)),
            "credits": Decimal(str(credits)),
            "closing": Decimal(str(closing)),
            "movement": Decimal(str(debits)) - Decimal(str(credits)),
        },
        "currency": {"transaction": "USD", "reporting": "USD"},
        "period": {"fiscal_year": 2024, "fiscal_period": 1, "calendar_month": "2024-01"},
        "integrity": {"source_row_hash": "test-hash", "balance_verified": True},
    }


class TestComplianceConfigWiring:
    def test_tb_tolerance_from_config(self):
        """With a big tolerance, a small TB imbalance should still pass CP-001."""
        # Default TRIAL_BALANCE_TOLERANCE is 0.01
        # Create TB records that are balanced within 0.01 but not within a tighter threshold
        records = [
            _make_tb_record(1000, 500, 500, 1000, is_control=False, code="100001"),
            _make_tb_record(2000, 300, 300.005, 1999.995, is_control=False, code="100002"),
        ]
        state = _base_state(trial_balance_records=records)
        result = compliance_specialist_node(state)
        scan = result["compliance_result"]
        cp001 = next(cp for cp in scan["control_points"] if cp["control_id"] == "CP-001")
        # With Decimal("0.01") tolerance, 0.005 difference should pass
        assert cp001["passed"] is True

        # Now patch to a very tight tolerance
        with patch(
            "sentient_ledger.agents.compliance_specialist.TRIAL_BALANCE_TOLERANCE",
            Decimal("0.001"),
        ):
            result2 = compliance_specialist_node(state)
            scan2 = result2["compliance_result"]
            cp001_tight = next(cp for cp in scan2["control_points"] if cp["control_id"] == "CP-001")
            # 0.005 > 0.001 → should fail
            assert cp001_tight["passed"] is False

    def test_asset_discrepancy_tolerance_from_config(self):
        """CP-004 uses tolerance from config for control account balance check."""
        # Create a control account where expected_closing - closing = 0.005
        # opening=1000, debits=500, credits=300 → expected_closing=1200
        # actual closing=1200.005 → diff=0.005, within default 0.01
        records = [
            _make_tb_record(1000, 500, 300, 1200.005, is_control=True, code="120000"),
        ]
        state = _base_state(trial_balance_records=records)
        result = compliance_specialist_node(state)
        assert len(result["asset_flags"]) == 0  # 0.005 <= 0.01

        # Tighten tolerance
        with patch(
            "sentient_ledger.agents.compliance_specialist.TRIAL_BALANCE_TOLERANCE",
            Decimal("0.001"),
        ):
            result2 = compliance_specialist_node(state)
            assert len(result2["asset_flags"]) >= 1  # 0.005 > 0.001
