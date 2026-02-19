"""Tests for the Compliance → Asset Warden trigger protocol."""

import uuid

import pytest

from sentient_ledger.graph.builder import build_reconciliation_graph
from sentient_ledger.models.enums import (
    AssetTriggerReason,
    AuthorityLevel,
    CommitResult,
    LedgerState,
    SignOffDecision,
)
from sentient_ledger.models.graph_state import create_initial_state


@pytest.fixture
def graph():
    return build_reconciliation_graph()


def _base_state(**overrides):
    state = create_initial_state(str(uuid.uuid4()))
    state["total_rows"] = 100
    state["malformed_pct"] = 0.5
    state["sign_off_decision"] = SignOffDecision.APPROVE
    state["sign_off_authority"] = AuthorityLevel.L4_CONTROLLER
    state["commit_result"] = CommitResult.ACK
    state.update(overrides)
    return state


def _make_discrepancy(reason, account="1520", self_healable=False, confidence=0.5):
    disc = {
        "reason": reason,
        "account": account,
        "account_name": f"Account {account}",
        "priority": "HIGH",
        "detail": {"expected": "33000", "actual": "36000", "variance": "3000", "variance_pct": 0.09, "period": "2026-01"},
    }
    if self_healable:
        disc["_self_healable"] = True
        disc["_confidence"] = confidence
    return [
        {
            "record_id": "rec-001",
            "account": {"code": account, "name": f"Account {account}", "category": "ASSET", "sub_category": "fixed", "is_control_account": True},
            "dimensions": {"business_unit": "BU-001", "composite_key": f"{account}-BU001"},
            "balances": {"opening": "100000", "debits": "50000", "credits": "30000", "closing": "120000"},
            "_discrepancy": disc,
            "period": {"fiscal_year": 2026, "fiscal_period": 1, "calendar_month": "2026-01"},
        },
    ]


class TestComplianceTriggersAssetInspection:
    def test_depreciation_variance_triggers_inspection(self, graph):
        state = _base_state(trial_balance_records=_make_discrepancy("DEPRECIATION_VARIANCE_EXCEEDS_THRESHOLD"))
        result = graph.invoke(state)
        assert result.get("inspection_report") is not None
        assert len(result.get("asset_flags", [])) > 0

    def test_missing_depreciation_triggers_inspection(self, graph):
        state = _base_state(trial_balance_records=_make_discrepancy("MISSING_DEPRECIATION_ENTRY"))
        result = graph.invoke(state)
        assert result.get("inspection_report") is not None

    def test_disposal_without_retirement_triggers_inspection(self, graph):
        state = _base_state(trial_balance_records=_make_discrepancy("DISPOSAL_WITHOUT_RETIREMENT"))
        result = graph.invoke(state)
        assert result.get("inspection_report") is not None

    def test_inspection_request_has_correct_trigger_reason(self, graph):
        state = _base_state(trial_balance_records=_make_discrepancy("MISSING_DEPRECIATION_ENTRY"))
        result = graph.invoke(state)
        request = result.get("inspection_request", {})
        assert request.get("trigger_reason") == "MISSING_DEPRECIATION_ENTRY"

    def test_inspection_request_has_discrepancy_detail(self, graph):
        state = _base_state(trial_balance_records=_make_discrepancy("DEPRECIATION_VARIANCE_EXCEEDS_THRESHOLD"))
        result = graph.invoke(state)
        request = result.get("inspection_request", {})
        detail = request.get("discrepancy_detail", {})
        assert detail.get("expected_balance") is not None
        assert detail.get("actual_balance") is not None
        assert detail.get("variance") is not None

    def test_no_discrepancy_skips_asset_inspection(self, graph):
        clean = [
            {
                "record_id": "rec-001",
                "account": {"code": "1000", "name": "Cash", "category": "ASSET", "sub_category": "current", "is_control_account": False},
                "dimensions": {"business_unit": "BU-001", "composite_key": "1000-BU001"},
                "balances": {"opening": "100000", "debits": "50000", "credits": "30000", "closing": "120000"},
                "period": {"fiscal_year": 2026, "fiscal_period": 1, "calendar_month": "2026-01"},
            },
        ]
        state = _base_state(trial_balance_records=clean)
        result = graph.invoke(state)
        assert result.get("inspection_report") is None


class TestSelfHealTrigger:
    def test_high_confidence_triggers_self_heal(self, graph):
        state = _base_state(trial_balance_records=_make_discrepancy(
            "DEPRECIATION_VARIANCE_EXCEEDS_THRESHOLD", self_healable=True, confidence=0.98
        ))
        result = graph.invoke(state)
        assert result.get("self_heal_correction") is not None

    def test_low_confidence_skips_self_heal(self, graph):
        state = _base_state(trial_balance_records=_make_discrepancy(
            "DEPRECIATION_VARIANCE_EXCEEDS_THRESHOLD", self_healable=True, confidence=0.80
        ))
        result = graph.invoke(state)
        # Low confidence: self_healable is True in request but confidence < 0.95
        # Asset warden will set self_healable=True and confidence=0.80 on finding
        # known_error_pattern_matched guard checks confidence >= 0.95, so goes to analysis
        assert result.get("self_heal_correction") is None

    def test_self_heal_produces_correction(self, graph):
        state = _base_state(trial_balance_records=_make_discrepancy(
            "DEPRECIATION_VARIANCE_EXCEEDS_THRESHOLD", self_healable=True, confidence=0.99
        ))
        result = graph.invoke(state)
        correction = result.get("self_heal_correction", {})
        assert correction.get("pattern_id") is not None
        assert correction.get("amount") is not None
