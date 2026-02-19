"""Shared fixtures for Sentient Ledger tests."""

import uuid

import pytest

from sentient_ledger.graph.builder import build_reconciliation_graph
from sentient_ledger.models.enums import (
    AccountCategory,
    AuthorityLevel,
    CommitResult,
    LedgerState,
    SignOffDecision,
)
from sentient_ledger.models.graph_state import create_initial_state


@pytest.fixture
def graph():
    """Compiled reconciliation state graph."""
    return build_reconciliation_graph()


@pytest.fixture
def trace_id():
    return str(uuid.uuid4())


@pytest.fixture
def base_state(trace_id):
    """Minimal valid initial state."""
    return create_initial_state(trace_id)


@pytest.fixture
def clean_tb_records():
    """Trial balance records with no discrepancies."""
    return [
        {
            "record_id": "rec-001",
            "account": {
                "code": "1000",
                "name": "Cash",
                "category": AccountCategory.ASSET,
                "sub_category": "current",
                "is_control_account": False,
            },
            "dimensions": {"business_unit": "BU-001", "composite_key": "1000-BU001"},
            "balances": {
                "opening": "100000",
                "debits": "50000",
                "credits": "30000",
                "closing": "120000",
                "movement": "20000",
            },
            "period": {"fiscal_year": 2026, "fiscal_period": 1, "calendar_month": "2026-01"},
        },
        {
            "record_id": "rec-002",
            "account": {
                "code": "2000",
                "name": "Accounts Payable",
                "category": AccountCategory.LIABILITY,
                "sub_category": "current",
                "is_control_account": False,
            },
            "dimensions": {"business_unit": "BU-001", "composite_key": "2000-BU001"},
            "balances": {
                "opening": "50000",
                "debits": "30000",
                "credits": "50000",
                "closing": "70000",
                "movement": "20000",
            },
            "period": {"fiscal_year": 2026, "fiscal_period": 1, "calendar_month": "2026-01"},
        },
    ]


@pytest.fixture
def discrepancy_tb_records():
    """Trial balance records with an asset discrepancy."""
    return [
        {
            "record_id": "rec-001",
            "account": {
                "code": "1520",
                "name": "Accumulated Depreciation",
                "category": "ASSET",
                "sub_category": "fixed",
                "is_control_account": True,
            },
            "dimensions": {"business_unit": "BU-001", "composite_key": "1520-BU001"},
            "balances": {
                "opening": "100000",
                "debits": "50000",
                "credits": "30000",
                "closing": "120000",
                "movement": "20000",
            },
            "_discrepancy": {
                "reason": "DEPRECIATION_VARIANCE_EXCEEDS_THRESHOLD",
                "account": "1520",
                "account_name": "Accumulated Depreciation",
                "priority": "HIGH",
                "detail": {
                    "expected": "33000",
                    "actual": "36000",
                    "variance": "3000",
                    "variance_pct": 0.09,
                    "period": "2026-01",
                },
            },
            "period": {"fiscal_year": 2026, "fiscal_period": 1, "calendar_month": "2026-01"},
        },
    ]


@pytest.fixture
def self_healable_tb_records():
    """Trial balance records with a self-healable discrepancy."""
    return [
        {
            "record_id": "rec-001",
            "account": {
                "code": "1520",
                "name": "Accumulated Depreciation",
                "category": "ASSET",
                "sub_category": "fixed",
                "is_control_account": True,
            },
            "dimensions": {"business_unit": "BU-001", "composite_key": "1520-BU001"},
            "balances": {
                "opening": "100000",
                "debits": "50000",
                "credits": "30000",
                "closing": "120000",
                "movement": "20000",
            },
            "_discrepancy": {
                "reason": "DEPRECIATION_VARIANCE_EXCEEDS_THRESHOLD",
                "account": "1520",
                "account_name": "Accumulated Depreciation",
                "priority": "HIGH",
                "detail": {
                    "expected": "33000",
                    "actual": "36000",
                    "variance": "3000",
                    "variance_pct": 0.09,
                    "period": "2026-01",
                },
                "_self_healable": True,
                "_confidence": 0.98,
            },
            "period": {"fiscal_year": 2026, "fiscal_period": 1, "calendar_month": "2026-01"},
        },
    ]
