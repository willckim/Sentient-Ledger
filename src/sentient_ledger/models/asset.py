"""Asset-related models: inspection requests, reports, and canonical records."""

from decimal import Decimal

from pydantic import BaseModel

from sentient_ledger.models.enums import (
    AssetStatus,
    AssetTriggerReason,
    DepreciationConvention,
    DepreciationMethod,
    Priority,
    SelfHealPatternId,
)


class GLAccountRef(BaseModel):
    account_code: str
    account_name: str = ""


class DiscrepancyDetail(BaseModel):
    expected_balance: Decimal
    actual_balance: Decimal
    variance: Decimal
    variance_pct: float
    period: str


class AssetInspectionRequest(BaseModel):
    request_id: str
    triggered_by: str = "COMPLIANCE_SPECIALIST"
    timestamp: str
    trigger_reason: AssetTriggerReason
    affected_accounts: list[GLAccountRef]
    discrepancy_detail: DiscrepancyDetail
    priority: Priority
    deadline_utc: str = ""


class AssetFinding(BaseModel):
    finding_id: str
    asset_id: str
    error_type: AssetTriggerReason
    description: str
    expected_value: Decimal
    actual_value: Decimal
    variance: Decimal
    self_healable: bool = False
    pattern_id: SelfHealPatternId | None = None
    confidence: float = 0.0


class AssetInspectionReport(BaseModel):
    report_id: str
    request_id: str
    timestamp: str
    findings: list[AssetFinding]
    summary: str = ""


class AssetIdentity(BaseModel):
    asset_id: str
    group: str
    description: str


class Acquisition(BaseModel):
    date: str
    cost: Decimal
    method: DepreciationMethod
    useful_life_months: int
    salvage_value: Decimal
    depreciable_base: Decimal = Decimal("0")
    convention: DepreciationConvention = DepreciationConvention.FULL_MONTH


class CurrentState(BaseModel):
    accumulated_depreciation: Decimal
    net_book_value: Decimal
    nbv_verified: bool = False
    status: AssetStatus = AssetStatus.ACTIVE
    last_depreciation_date: str | None = None
    remaining_life_months: int = 0


class AssetIntegrity(BaseModel):
    source_row_hash: str = ""
    depreciation_method_valid: bool = True
    lifecycle_consistent: bool = True


class CanonicalAssetRecord(BaseModel):
    record_id: str
    source: str = "DYNAMICS_365"
    ingestion_id: str = ""
    ingested_at: str = ""
    identity: AssetIdentity
    acquisition: Acquisition
    current_state: CurrentState
    integrity: AssetIntegrity = AssetIntegrity()
