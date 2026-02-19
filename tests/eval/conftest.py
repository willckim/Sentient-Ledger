"""Fixtures for the eval test suite: scenario loading and batch execution."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sentient_ledger.engine.comparator import aggregate_metrics, compare_results
from sentient_ledger.engine.detector import detect_errors
from sentient_ledger.models.eval import (
    DepreciationEntry,
    EvalResult,
    GLBalance,
    ScenarioAssetRecord,
    SyntheticScenario,
)

SCENARIOS_DIR = Path(__file__).parent / "scenarios"


def _load_scenarios_from_dir(directory: Path) -> list[SyntheticScenario]:
    """Load all JSON scenario files from a directory."""
    scenarios = []
    if not directory.exists():
        return scenarios
    for f in sorted(directory.glob("*.json")):
        data = json.loads(f.read_text(encoding="utf-8"))
        scenarios.append(SyntheticScenario(**data))
    return scenarios


def load_all_scenarios() -> list[SyntheticScenario]:
    """Load all 54 scenarios from all category subdirectories."""
    scenarios = []
    for subdir in sorted(SCENARIOS_DIR.iterdir()):
        if subdir.is_dir():
            scenarios.extend(_load_scenarios_from_dir(subdir))
    return scenarios


def run_scenario(scenario: SyntheticScenario) -> EvalResult:
    """Run a single scenario through detector + comparator."""
    assets = scenario.input.asset_register
    schedule = scenario.input.depreciation_schedule
    gl_balances = scenario.input.gl_balances

    # Convert Pydantic models to the detector's expected types
    asset_records = [ScenarioAssetRecord(**a.model_dump()) for a in assets]
    depr_entries = [DepreciationEntry(**e.model_dump()) for e in schedule]
    gl_entries = [GLBalance(**g.model_dump()) for g in gl_balances]

    as_of = None
    if scenario.input.as_of_date:
        from sentient_ledger.engine.detector import _parse_date
        as_of = _parse_date(scenario.input.as_of_date)

    detection = detect_errors(asset_records, gl_entries, depr_entries, as_of)
    result = compare_results(scenario, detection)
    return result


@pytest.fixture(scope="session")
def all_scenarios() -> list[SyntheticScenario]:
    """Session-scoped: load all scenario JSON files."""
    return load_all_scenarios()


@pytest.fixture(scope="session")
def all_results(all_scenarios) -> list[EvalResult]:
    """Session-scoped: run all scenarios and collect results."""
    return [run_scenario(s) for s in all_scenarios]


@pytest.fixture(scope="session")
def aggregate(all_results):
    """Session-scoped: compute aggregate metrics."""
    return aggregate_metrics(all_results)
