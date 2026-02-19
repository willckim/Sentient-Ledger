"""Asset Warden agent.

Deterministic: inspects assets referenced by the inspection request
and produces findings. May flag findings as self-healable.

P1 upgrade: when asset_register data is present in state, delegates to
the real detector engine. Otherwise, falls back to the P0 stub logic.
"""

from decimal import Decimal

from sentient_ledger.agents.base import make_envelope, new_id, now_iso
from sentient_ledger.models.asset import AssetFinding, AssetInspectionReport
from sentient_ledger.models.enums import (
    AgentId,
    AssetTriggerReason,
    LedgerState,
    SelfHealPatternId,
)
from sentient_ledger.models.graph_state import ReconciliationState


def asset_warden_node(state: ReconciliationState) -> dict:
    """Inspect assets based on the inspection request.

    If asset_register is present in state, uses the real detector engine.
    Otherwise, falls back to stub logic for backward compatibility.
    """
    # Check for detector path (P1)
    asset_register = state.get("asset_register")
    if asset_register:
        return _detector_path(state)

    # Fallback: P0 stub path
    return _stub_path(state)


def _detector_path(state: ReconciliationState) -> dict:
    """P1 path: delegate to the real error detector."""
    from sentient_ledger.engine.detector import detect_errors, _parse_date
    from sentient_ledger.models.eval import (
        DepreciationEntry,
        GLBalance,
        ScenarioAssetRecord,
    )

    trace_id = state.get("trace_id", "")
    raw_register = state.get("asset_register", [])
    raw_schedule = state.get("depreciation_schedule", [])
    raw_gl = state.get("gl_balances", [])

    # Parse into typed models
    assets = [ScenarioAssetRecord(**r) for r in raw_register]
    schedule = [DepreciationEntry(**e) for e in raw_schedule]
    gl_balances = [GLBalance(**g) for g in raw_gl]

    result = detect_errors(assets, gl_balances, schedule)

    # Convert DetectionFindings to AssetFindings for the report
    findings = []
    for f in result.findings:
        finding = AssetFinding(
            finding_id=f.finding_id,
            asset_id=f.affected_asset_ids[0] if f.affected_asset_ids else "UNKNOWN",
            error_type=f.error_type,
            description=f.description,
            expected_value=f.expected_value or Decimal("0"),
            actual_value=f.actual_value or Decimal("0"),
            variance=f.variance or Decimal("0"),
            self_healable=f.self_healable,
            pattern_id=f.pattern_id,
            confidence=f.confidence,
        )
        findings.append(finding)

    request = state.get("inspection_request", {})
    report = AssetInspectionReport(
        report_id=new_id(),
        request_id=request.get("request_id", ""),
        timestamp=now_iso(),
        findings=findings,
        summary=f"Detector found {len(findings)} issue(s).",
    )

    envelope = make_envelope(
        source_agent=AgentId.ASSET_WARDEN,
        target_agent=AgentId.FINANCIAL_ANALYST,
        state_from=LedgerState.ASSET_INSPECTION,
        state_to=LedgerState.ANALYSIS,
        payload=report.model_dump(),
        trace_id=trace_id,
    )

    return {
        "current_state": LedgerState.ASSET_INSPECTION,
        "inspection_report": report.model_dump(),
        "envelopes": [envelope],
    }


def _stub_path(state: ReconciliationState) -> dict:
    """P0 stub path: generates findings from the inspection request data."""
    trace_id = state.get("trace_id", "")
    request = state.get("inspection_request", {})
    detail = request.get("discrepancy_detail", {})
    trigger_reason = request.get("trigger_reason", "DEPRECIATION_VARIANCE_EXCEEDS_THRESHOLD")

    variance = Decimal(str(detail.get("variance", 0)))

    # Map trigger reasons to known self-heal patterns
    pattern_map = {
        "DEPRECIATION_VARIANCE_EXCEEDS_THRESHOLD": SelfHealPatternId.AW_001,
        "MISSING_DEPRECIATION_ENTRY": SelfHealPatternId.AW_002,
        "USEFUL_LIFE_MISMATCH": SelfHealPatternId.AW_003,
    }

    # Check for explicit healability flags in the inspection request
    is_self_healable = request.get("_self_healable", False)
    confidence = request.get("_confidence", 0.5)
    pattern_id = pattern_map.get(trigger_reason)

    finding = AssetFinding(
        finding_id=new_id(),
        asset_id=request.get("affected_accounts", [{}])[0].get("account_code", "UNKNOWN")
        if request.get("affected_accounts") else "UNKNOWN",
        error_type=AssetTriggerReason(trigger_reason),
        description=f"Discrepancy detected: {trigger_reason}",
        expected_value=Decimal(str(detail.get("expected_balance", 0))),
        actual_value=Decimal(str(detail.get("actual_balance", 0))),
        variance=abs(variance),
        self_healable=is_self_healable,
        pattern_id=pattern_id if is_self_healable else None,
        confidence=confidence,
    )

    report = AssetInspectionReport(
        report_id=new_id(),
        request_id=request.get("request_id", ""),
        timestamp=now_iso(),
        findings=[finding],
        summary=f"Inspection complete. {len([finding])} finding(s).",
    )

    envelope = make_envelope(
        source_agent=AgentId.ASSET_WARDEN,
        target_agent=AgentId.FINANCIAL_ANALYST,
        state_from=LedgerState.ASSET_INSPECTION,
        state_to=LedgerState.ANALYSIS,
        payload=report.model_dump(),
        trace_id=trace_id,
    )

    return {
        "current_state": LedgerState.ASSET_INSPECTION,
        "inspection_report": report.model_dump(),
        "envelopes": [envelope],
    }
