"""Unit tests for the eval comparator."""

from decimal import Decimal

import pytest

from sentient_ledger.engine.comparator import aggregate_metrics, compare_results
from sentient_ledger.models.enums import (
    AssetTriggerReason,
    DepreciationConvention,
    DepreciationMethod,
    Priority,
    ScenarioCategory,
    SelfHealPatternId,
)
from sentient_ledger.models.eval import (
    AggregateMetrics,
    CorrectionTolerance,
    DetectionFinding,
    DetectionResult,
    EvalCriteria,
    EvalResult,
    ExpectedCorrection,
    ExpectedDetection,
    InjectedError,
    ScenarioAssetRecord,
    ScenarioExpectedOutput,
    ScenarioInput,
    SyntheticScenario,
)


def _make_scenario(
    detections: list[ExpectedDetection],
    corrections: list[ExpectedCorrection] | None = None,
    severity: Priority = Priority.HIGH,
) -> SyntheticScenario:
    errors = [
        InjectedError(
            error_id=d.error_id,
            error_type=d.error_type,
            description="test",
            affected_asset_ids=d.affected_asset_ids,
        )
        for d in detections
    ]
    return SyntheticScenario(
        scenario_id="TEST-001",
        name="Test scenario",
        category=ScenarioCategory.CALC,
        severity=severity,
        input=ScenarioInput(
            asset_register=[ScenarioAssetRecord(
                asset_id="A-001",
                acquisition_date="2024-01-01",
                cost=Decimal("100000"),
                useful_life_months=120,
            )],
            depreciation_schedule=[],
        ),
        expected=ScenarioExpectedOutput(
            injected_errors=errors,
            expected_detections=detections,
            expected_corrections=corrections or [],
        ),
    )


class TestCompareResults:
    def test_perfect_detection(self):
        """All expected errors detected → recall=1.0, precision=1.0."""
        scenario = _make_scenario([
            ExpectedDetection(
                error_id="E-001",
                error_type=AssetTriggerReason.DEPRECIATION_VARIANCE_EXCEEDS_THRESHOLD,
                affected_asset_ids=["A-001"],
            ),
        ])
        detection = DetectionResult(findings=[
            DetectionFinding(
                finding_id="F-001",
                error_type=AssetTriggerReason.DEPRECIATION_VARIANCE_EXCEEDS_THRESHOLD,
                affected_asset_ids=["A-001"],
            ),
        ])

        result = compare_results(scenario, detection)
        assert result.metrics.recall == 1.0
        assert result.metrics.precision == 1.0
        assert result.metrics.true_positives == 1
        assert result.metrics.false_negatives == 0
        assert result.metrics.false_positives == 0

    def test_missed_detection(self):
        """Expected error not found → FN, recall < 1.0."""
        scenario = _make_scenario([
            ExpectedDetection(
                error_id="E-001",
                error_type=AssetTriggerReason.MISSING_DEPRECIATION_ENTRY,
                affected_asset_ids=["A-001"],
            ),
        ])
        detection = DetectionResult(findings=[])

        result = compare_results(scenario, detection)
        assert result.metrics.recall == 0.0
        assert result.metrics.false_negatives == 1
        assert result.passed is False

    def test_false_positive(self):
        """Extra finding not in expected → FP."""
        scenario = _make_scenario([
            ExpectedDetection(
                error_id="E-001",
                error_type=AssetTriggerReason.DEPRECIATION_VARIANCE_EXCEEDS_THRESHOLD,
                affected_asset_ids=["A-001"],
            ),
        ])
        detection = DetectionResult(findings=[
            DetectionFinding(
                finding_id="F-001",
                error_type=AssetTriggerReason.DEPRECIATION_VARIANCE_EXCEEDS_THRESHOLD,
                affected_asset_ids=["A-001"],
            ),
            DetectionFinding(
                finding_id="F-002",
                error_type=AssetTriggerReason.USEFUL_LIFE_MISMATCH,
                affected_asset_ids=["A-001"],
            ),
        ])

        result = compare_results(scenario, detection)
        assert result.metrics.true_positives == 1
        assert result.metrics.false_positives == 1
        assert result.metrics.precision < 1.0

    def test_no_expected_no_found(self):
        """Clean scenario: no expected, no found → passes."""
        scenario = _make_scenario([])
        detection = DetectionResult(findings=[])

        result = compare_results(scenario, detection)
        assert result.metrics.recall == 1.0
        assert result.metrics.precision == 1.0
        assert result.passed is True

    def test_correction_accuracy(self):
        """Correction amounts should be compared when available."""
        scenario = _make_scenario(
            detections=[
                ExpectedDetection(
                    error_id="E-001",
                    error_type=AssetTriggerReason.DEPRECIATION_VARIANCE_EXCEEDS_THRESHOLD,
                    affected_asset_ids=["A-001"],
                ),
            ],
            corrections=[
                ExpectedCorrection(
                    error_id="E-001",
                    corrected_amount=Decimal("90000"),
                ),
            ],
        )
        detection = DetectionResult(findings=[
            DetectionFinding(
                finding_id="F-001",
                error_type=AssetTriggerReason.DEPRECIATION_VARIANCE_EXCEEDS_THRESHOLD,
                affected_asset_ids=["A-001"],
                corrected_amount=Decimal("90000"),
            ),
        ])

        result = compare_results(scenario, detection)
        assert result.metrics.correction_accuracy == 1.0
        assert result.metrics.mean_absolute_error == Decimal("0")


class TestAggregateMetrics:
    def test_aggregate_all_passing(self):
        """All passing results → gate passes."""
        results = [
            EvalResult(
                scenario_id=f"S-{i}",
                category=ScenarioCategory.CALC,
                severity=Priority.CRITICAL if i < 3 else Priority.HIGH,
                passed=True,
                metrics=_make_metrics(tp=1, fp=0, fn=0),
            )
            for i in range(10)
        ]
        agg = aggregate_metrics(results)
        assert agg.gate_passed is True
        assert agg.overall_recall == 1.0
        assert agg.critical_recall == 1.0

    def test_aggregate_with_failures(self):
        """Some failures → may not pass gate."""
        results = [
            EvalResult(
                scenario_id="S-PASS",
                category=ScenarioCategory.CALC,
                severity=Priority.HIGH,
                passed=True,
                metrics=_make_metrics(tp=1, fp=0, fn=0),
            ),
            EvalResult(
                scenario_id="S-FAIL",
                category=ScenarioCategory.CALC,
                severity=Priority.HIGH,
                passed=False,
                metrics=_make_metrics(tp=0, fp=0, fn=1),
            ),
        ]
        agg = aggregate_metrics(results)
        assert agg.overall_recall == 0.5
        assert agg.gate_passed is False

    def test_empty_results(self):
        agg = aggregate_metrics([])
        assert agg.gate_passed is False
        assert agg.total_scenarios == 0


def _make_metrics(tp=0, fp=0, fn=0):
    from sentient_ledger.models.eval import EvalMetrics
    recall = tp / (tp + fn) if (tp + fn) > 0 else 1.0
    precision = tp / (tp + fp) if (tp + fp) > 0 else 1.0
    f1 = 2 * recall * precision / (recall + precision) if (recall + precision) > 0 else 0.0
    return EvalMetrics(
        true_positives=tp,
        false_positives=fp,
        false_negatives=fn,
        recall=recall,
        precision=precision,
        f1=f1,
        correction_accuracy=1.0,
    )
