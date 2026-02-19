"""Parametrized 54-scenario test runner.

Each scenario JSON is loaded, run through the detector, and compared
against expected output using the comparator.
"""

from __future__ import annotations

import pytest

from tests.eval.conftest import load_all_scenarios, run_scenario

# Collect scenario IDs for parametrization
_scenarios = load_all_scenarios()


@pytest.mark.parametrize(
    "scenario",
    _scenarios,
    ids=[s.scenario_id for s in _scenarios],
)
def test_scenario(scenario):
    """Run a single scenario and assert it passes its eval criteria."""
    result = run_scenario(scenario)

    # Diagnostic info on failure
    if not result.passed:
        missed = result.missed_ids
        fps = result.false_positive_ids
        msg = (
            f"\nScenario {scenario.scenario_id} ({scenario.name}) FAILED\n"
            f"  Recall:    {result.metrics.recall} (min: {scenario.eval_criteria.min_recall})\n"
            f"  Precision: {result.metrics.precision} (min: {scenario.eval_criteria.min_precision})\n"
            f"  Max Error: {result.metrics.max_error} (max: {scenario.eval_criteria.max_correction_error})\n"
            f"  TP={result.metrics.true_positives} FP={result.metrics.false_positives} FN={result.metrics.false_negatives}\n"
            f"  Missed:    {missed}\n"
            f"  FP IDs:    {fps}\n"
        )
        pytest.fail(msg)
