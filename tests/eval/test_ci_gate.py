"""CI/CD gate tests: aggregate metrics must meet thresholds."""

from __future__ import annotations

import pytest

from sentient_ledger.config import (
    EVAL_GATE_CORRECTION_ACCURACY,
    EVAL_GATE_CRITICAL_RECALL,
    EVAL_GATE_MAX_ERROR,
    EVAL_GATE_PRECISION,
    EVAL_GATE_RECALL,
)
from sentient_ledger.models.enums import Priority
from tests.eval.conftest import load_all_scenarios, run_scenario
from sentient_ledger.engine.comparator import aggregate_metrics


@pytest.fixture(scope="module")
def _all_results():
    scenarios = load_all_scenarios()
    return [run_scenario(s) for s in scenarios]


@pytest.fixture(scope="module")
def _aggregate(_all_results):
    return aggregate_metrics(_all_results)


def test_overall_recall(_aggregate):
    assert _aggregate.overall_recall >= EVAL_GATE_RECALL, (
        f"Overall recall {_aggregate.overall_recall} < gate {EVAL_GATE_RECALL}"
    )


def test_overall_precision(_aggregate):
    assert _aggregate.overall_precision >= EVAL_GATE_PRECISION, (
        f"Overall precision {_aggregate.overall_precision} < gate {EVAL_GATE_PRECISION}"
    )


def test_critical_recall(_all_results):
    """All CRITICAL scenarios must achieve Recall=1.0."""
    critical = [r for r in _all_results if r.severity == Priority.CRITICAL]
    assert len(critical) > 0, "No CRITICAL scenarios found"

    for r in critical:
        assert r.metrics.recall >= EVAL_GATE_CRITICAL_RECALL, (
            f"CRITICAL scenario {r.scenario_id} recall={r.metrics.recall} < {EVAL_GATE_CRITICAL_RECALL}"
        )


def test_correction_accuracy(_aggregate):
    assert _aggregate.correction_accuracy >= EVAL_GATE_CORRECTION_ACCURACY, (
        f"Correction accuracy {_aggregate.correction_accuracy} < gate {EVAL_GATE_CORRECTION_ACCURACY}"
    )


def test_max_error(_aggregate):
    assert _aggregate.max_error <= EVAL_GATE_MAX_ERROR, (
        f"Max error {_aggregate.max_error} > gate {EVAL_GATE_MAX_ERROR}"
    )


def test_gate_passed(_aggregate):
    """The aggregate gate_passed flag must be True."""
    assert _aggregate.gate_passed, (
        f"Gate FAILED: recall={_aggregate.overall_recall}, "
        f"precision={_aggregate.overall_precision}, "
        f"critical_recall={_aggregate.critical_recall}, "
        f"correction_accuracy={_aggregate.correction_accuracy}, "
        f"max_error={_aggregate.max_error}"
    )


def test_all_scenarios_present(_all_results):
    """Verify we have all 54 scenarios."""
    assert len(_all_results) >= 54, (
        f"Expected at least 54 scenarios, found {len(_all_results)}"
    )
