"""Evaluation framework models for synthetic scenario testing."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field

from sentient_ledger.models.enums import (
    AssetStatus,
    AssetTriggerReason,
    DepreciationConvention,
    DepreciationMethod,
    Priority,
    ScenarioCategory,
    SelfHealPatternId,
)


# --- Scenario input models ---


class ScenarioAssetRecord(BaseModel):
    """Asset register entry used as scenario input."""

    asset_id: str
    description: str = ""
    acquisition_date: str
    cost: Decimal
    salvage_value: Decimal = Decimal("0")
    useful_life_months: int
    depreciation_method: DepreciationMethod = DepreciationMethod.STRAIGHT_LINE
    convention: DepreciationConvention = DepreciationConvention.FULL_MONTH
    status: AssetStatus = AssetStatus.ACTIVE
    disposal_date: str | None = None
    disposal_proceeds: Decimal | None = None
    entity_id: str = "ENTITY-001"
    group: str = "PP&E"


class DepreciationEntry(BaseModel):
    """A single depreciation schedule entry."""

    asset_id: str
    period: str  # YYYY-MM
    amount: Decimal
    accumulated: Decimal
    net_book_value: Decimal


class GLBalance(BaseModel):
    """General ledger balance for an account/period."""

    account_code: str
    account_name: str = ""
    period: str  # YYYY-MM
    balance: Decimal
    entity_id: str = "ENTITY-001"


class ScenarioInput(BaseModel):
    """All input data for a synthetic scenario."""

    asset_register: list[ScenarioAssetRecord]
    depreciation_schedule: list[DepreciationEntry]
    gl_balances: list[GLBalance] = Field(default_factory=list)
    as_of_date: str | None = None


# --- Expected output models ---


class InjectedError(BaseModel):
    """Describes an error intentionally injected into the scenario."""

    error_id: str
    error_type: AssetTriggerReason
    description: str
    affected_asset_ids: list[str]
    affected_periods: list[str] = Field(default_factory=list)
    magnitude: Decimal | None = None


class ExpectedDetection(BaseModel):
    """An error the detector should find."""

    error_id: str
    error_type: AssetTriggerReason
    affected_asset_ids: list[str]
    min_confidence: float = 0.5
    pattern_id: SelfHealPatternId | None = None


class CorrectionTolerance(BaseModel):
    """Acceptable tolerance for correction amounts."""

    absolute: Decimal = Decimal("1.00")
    relative: Decimal = Decimal("0.001")  # 0.1%


class ExpectedCorrection(BaseModel):
    """Expected correction for an injected error."""

    error_id: str
    corrected_amount: Decimal
    tolerance: CorrectionTolerance = Field(default_factory=CorrectionTolerance)


class ExpectedClassification(BaseModel):
    """Expected classification/categorization of detected error."""

    error_id: str
    expected_trigger_reason: AssetTriggerReason
    expected_self_healable: bool = True


class ScenarioExpectedOutput(BaseModel):
    """Full expected output for a scenario."""

    injected_errors: list[InjectedError]
    expected_detections: list[ExpectedDetection]
    expected_corrections: list[ExpectedCorrection] = Field(default_factory=list)
    expected_classifications: list[ExpectedClassification] = Field(default_factory=list)


# --- Eval criteria ---


class EvalCriteria(BaseModel):
    """Thresholds that this specific scenario must meet."""

    min_recall: float = 0.98
    min_precision: float = 0.95
    max_correction_error: Decimal = Decimal("1.00")


# --- Top-level scenario model ---


class SyntheticScenario(BaseModel):
    """A complete synthetic test scenario."""

    scenario_id: str
    name: str
    description: str = ""
    category: ScenarioCategory
    severity: Priority = Priority.HIGH
    input: ScenarioInput
    expected: ScenarioExpectedOutput
    eval_criteria: EvalCriteria = Field(default_factory=EvalCriteria)
    metadata: dict[str, Any] = Field(default_factory=dict)


# --- Detection result (output of detector) ---


class DetectionFinding(BaseModel):
    """A single finding from the detector."""

    finding_id: str
    error_type: AssetTriggerReason
    affected_asset_ids: list[str]
    description: str = ""
    expected_value: Decimal | None = None
    actual_value: Decimal | None = None
    variance: Decimal | None = None
    confidence: float = 0.0
    self_healable: bool = False
    pattern_id: SelfHealPatternId | None = None
    corrected_amount: Decimal | None = None


class DetectionResult(BaseModel):
    """Full output of the detector for a scenario."""

    findings: list[DetectionFinding] = Field(default_factory=list)
    errors_detected: int = 0
    execution_time_ms: float = 0.0


# --- Eval result models ---


class EvalMetrics(BaseModel):
    """Evaluation metrics for a single scenario or aggregate."""

    true_positives: int = 0
    false_positives: int = 0
    false_negatives: int = 0
    recall: float = 0.0
    precision: float = 0.0
    f1: float = 0.0
    correction_accuracy: float = 0.0
    mean_absolute_error: Decimal = Decimal("0")
    max_error: Decimal = Decimal("0")
    latency_ms: float = 0.0


class EvalResult(BaseModel):
    """Evaluation result for a single scenario."""

    scenario_id: str = ""
    category: ScenarioCategory = ScenarioCategory.CALC
    severity: Priority = Priority.HIGH
    passed: bool = False
    metrics: EvalMetrics = Field(default_factory=EvalMetrics)
    detected_ids: list[str] = Field(default_factory=list)
    missed_ids: list[str] = Field(default_factory=list)
    false_positive_ids: list[str] = Field(default_factory=list)


class AggregateMetrics(BaseModel):
    """Aggregate metrics across all scenarios."""

    total_scenarios: int = 0
    passed_scenarios: int = 0
    overall_recall: float = 0.0
    overall_precision: float = 0.0
    overall_f1: float = 0.0
    critical_recall: float = 0.0
    correction_accuracy: float = 0.0
    mean_absolute_error: Decimal = Decimal("0")
    max_error: Decimal = Decimal("0")
    avg_latency_ms: float = 0.0
    gate_passed: bool = False
