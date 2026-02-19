"""Eval comparator: compares detector output against expected results and computes metrics."""

from __future__ import annotations

from decimal import Decimal

from sentient_ledger.config import (
    EVAL_GATE_CORRECTION_ACCURACY,
    EVAL_GATE_CRITICAL_RECALL,
    EVAL_GATE_MAX_ERROR,
    EVAL_GATE_PRECISION,
    EVAL_GATE_RECALL,
)
from sentient_ledger.models.enums import Priority
from sentient_ledger.models.eval import (
    AggregateMetrics,
    DetectionResult,
    EvalMetrics,
    EvalResult,
    SyntheticScenario,
)


def compare_results(scenario: SyntheticScenario, detection: DetectionResult) -> EvalResult:
    """Compare detector output against scenario expected output.

    Matching: expected detection matched to finding by (error_type, affected_asset_ids intersection).
    Matched=TP, unmatched expected=FN, unmatched detected=FP.
    """
    expected_detections = scenario.expected.expected_detections
    expected_corrections = {c.error_id: c for c in scenario.expected.expected_corrections}
    findings = detection.findings

    # Track which findings and expected detections have been matched
    matched_expected: set[str] = set()
    matched_findings: set[str] = set()
    correction_errors: list[Decimal] = []

    # Match expected detections to findings
    for exp in expected_detections:
        exp_assets = set(exp.affected_asset_ids)
        best_match = None
        best_overlap = 0

        for finding in findings:
            if finding.finding_id in matched_findings:
                continue
            # Match by error_type and asset_id intersection
            if finding.error_type == exp.error_type:
                overlap = len(exp_assets & set(finding.affected_asset_ids))
                if overlap > best_overlap:
                    best_overlap = overlap
                    best_match = finding

        # If no exact type match, try matching by asset overlap alone (more lenient)
        if best_match is None:
            for finding in findings:
                if finding.finding_id in matched_findings:
                    continue
                overlap = len(exp_assets & set(finding.affected_asset_ids))
                if overlap > 0:
                    best_overlap = overlap
                    best_match = finding
                    break

        if best_match is not None:
            matched_expected.add(exp.error_id)
            matched_findings.add(best_match.finding_id)

            # Check correction accuracy if applicable
            if exp.error_id in expected_corrections and best_match.corrected_amount is not None:
                exp_correction = expected_corrections[exp.error_id]
                error = abs(best_match.corrected_amount - exp_correction.corrected_amount)
                correction_errors.append(error)

    # Calculate metrics
    tp = len(matched_expected)
    fn = len(expected_detections) - tp
    fp = len(findings) - len(matched_findings)

    recall = tp / (tp + fn) if (tp + fn) > 0 else 1.0
    precision = tp / (tp + fp) if (tp + fp) > 0 else 1.0
    f1 = 2 * recall * precision / (recall + precision) if (recall + precision) > 0 else 0.0

    # Correction accuracy
    if correction_errors:
        mean_abs_error = sum(correction_errors) / len(correction_errors)
        max_error = max(correction_errors)
        within_tolerance = sum(
            1 for e in correction_errors
            if e <= scenario.eval_criteria.max_correction_error
        )
        correction_accuracy = within_tolerance / len(correction_errors)
    else:
        mean_abs_error = Decimal("0")
        max_error = Decimal("0")
        correction_accuracy = 1.0

    detected_ids = sorted(matched_expected)
    missed_ids = sorted(set(e.error_id for e in expected_detections) - matched_expected)
    fp_ids = sorted(set(f.finding_id for f in findings) - matched_findings)

    metrics = EvalMetrics(
        true_positives=tp,
        false_positives=fp,
        false_negatives=fn,
        recall=round(recall, 4),
        precision=round(precision, 4),
        f1=round(f1, 4),
        correction_accuracy=round(correction_accuracy, 4),
        mean_absolute_error=mean_abs_error,
        max_error=max_error,
        latency_ms=detection.execution_time_ms,
    )

    # Determine if scenario passed
    criteria = scenario.eval_criteria
    passed = (
        recall >= criteria.min_recall
        and precision >= criteria.min_precision
        and max_error <= criteria.max_correction_error
    )

    return EvalResult(
        scenario_id=scenario.scenario_id,
        category=scenario.category,
        severity=scenario.severity,
        passed=passed,
        metrics=metrics,
        detected_ids=detected_ids,
        missed_ids=missed_ids,
        false_positive_ids=fp_ids,
    )


def aggregate_metrics(results: list[EvalResult]) -> AggregateMetrics:
    """Aggregate metrics across all scenario results and check gate thresholds."""
    if not results:
        return AggregateMetrics(gate_passed=False)

    total_tp = sum(r.metrics.true_positives for r in results)
    total_fp = sum(r.metrics.false_positives for r in results)
    total_fn = sum(r.metrics.false_negatives for r in results)

    overall_recall = total_tp / (total_tp + total_fn) if (total_tp + total_fn) > 0 else 1.0
    overall_precision = total_tp / (total_tp + total_fp) if (total_tp + total_fp) > 0 else 1.0
    overall_f1 = (
        2 * overall_recall * overall_precision / (overall_recall + overall_precision)
        if (overall_recall + overall_precision) > 0
        else 0.0
    )

    # Critical recall: recall only over CRITICAL scenarios
    critical_results = [r for r in results if r.severity == Priority.CRITICAL]
    if critical_results:
        crit_tp = sum(r.metrics.true_positives for r in critical_results)
        crit_fn = sum(r.metrics.false_negatives for r in critical_results)
        critical_recall = crit_tp / (crit_tp + crit_fn) if (crit_tp + crit_fn) > 0 else 1.0
    else:
        critical_recall = 1.0

    # Correction accuracy
    correction_accs = [r.metrics.correction_accuracy for r in results if r.metrics.correction_accuracy > 0]
    avg_correction_accuracy = sum(correction_accs) / len(correction_accs) if correction_accs else 1.0

    # Error metrics
    all_mae = [r.metrics.mean_absolute_error for r in results]
    overall_mae = sum(all_mae) / len(all_mae) if all_mae else Decimal("0")
    overall_max_error = max((r.metrics.max_error for r in results), default=Decimal("0"))

    # Latency
    latencies = [r.metrics.latency_ms for r in results if r.metrics.latency_ms > 0]
    avg_latency = sum(latencies) / len(latencies) if latencies else 0.0

    passed_count = sum(1 for r in results if r.passed)

    # Gate check
    gate_passed = (
        overall_recall >= EVAL_GATE_RECALL
        and overall_precision >= EVAL_GATE_PRECISION
        and critical_recall >= EVAL_GATE_CRITICAL_RECALL
        and avg_correction_accuracy >= EVAL_GATE_CORRECTION_ACCURACY
        and overall_max_error <= EVAL_GATE_MAX_ERROR
    )

    return AggregateMetrics(
        total_scenarios=len(results),
        passed_scenarios=passed_count,
        overall_recall=round(overall_recall, 4),
        overall_precision=round(overall_precision, 4),
        overall_f1=round(overall_f1, 4),
        critical_recall=round(critical_recall, 4),
        correction_accuracy=round(avg_correction_accuracy, 4),
        mean_absolute_error=overall_mae,
        max_error=overall_max_error,
        avg_latency_ms=round(avg_latency, 2),
        gate_passed=gate_passed,
    )
