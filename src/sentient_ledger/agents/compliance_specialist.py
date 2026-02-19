"""Compliance Specialist agent stub.

Deterministic: inspects trial balance data for asset discrepancies
and emits AssetInspectionRequest when found.
"""

from decimal import Decimal

from sentient_ledger.agents.base import make_envelope, new_id, now_iso
from sentient_ledger.config import TRIAL_BALANCE_TOLERANCE
from sentient_ledger.models.asset import (
    AssetInspectionRequest,
    DiscrepancyDetail,
    GLAccountRef,
)
from sentient_ledger.models.compliance import (
    ComplianceScanResult,
    ControlPointResult,
)
from sentient_ledger.models.enums import (
    AgentId,
    AssetTriggerReason,
    LedgerState,
    Priority,
)
from sentient_ledger.models.graph_state import ReconciliationState


def compliance_specialist_node(state: ReconciliationState) -> dict:
    """Run compliance checks on ingested trial balance data.

    Scans for asset discrepancies. If found, populates asset_flags
    and creates an inspection_request for the Asset Warden.
    """
    trace_id = state.get("trace_id", "")
    records = state.get("trial_balance_records", [])

    control_points = []
    asset_flags: list[str] = []
    inspection_request = None

    # CP1: Trial balance foots (debits == credits)
    total_debits = sum(Decimal(str(r.get("balances", {}).get("debits", 0))) for r in records)
    total_credits = sum(Decimal(str(r.get("balances", {}).get("credits", 0))) for r in records)
    tb_foots = abs(total_debits - total_credits) <= TRIAL_BALANCE_TOLERANCE
    control_points.append(ControlPointResult(
        control_id="CP-001",
        description="Trial balance foots (debits == credits)",
        passed=tb_foots,
        detail=f"Debits={total_debits}, Credits={total_credits}",
    ))

    # CP4: Fixed-asset sub-ledger ties to GL control accounts
    # Stub: check if any record has asset_discrepancy flag in its data
    for r in records:
        account = r.get("account", {})
        if account.get("is_control_account") and account.get("category") == "ASSET":
            balances = r.get("balances", {})
            opening = Decimal(str(balances.get("opening", 0)))
            closing = Decimal(str(balances.get("closing", 0)))
            debits = Decimal(str(balances.get("debits", 0)))
            credits = Decimal(str(balances.get("credits", 0)))
            expected_closing = opening + debits - credits
            if abs(expected_closing - closing) > TRIAL_BALANCE_TOLERANCE:
                flag = f"ASSET_DISCREPANCY:{account.get('code', 'UNKNOWN')}"
                asset_flags.append(flag)

    # Also check for explicit discrepancy markers in records
    for r in records:
        discrepancy = r.get("_discrepancy")
        if discrepancy:
            flag = f"{discrepancy.get('reason', 'UNKNOWN')}:{discrepancy.get('account', '')}"
            if flag not in asset_flags:
                asset_flags.append(flag)

            if not inspection_request:
                detail = discrepancy.get("detail", {})
                inspection_request = AssetInspectionRequest(
                    request_id=new_id(),
                    timestamp=now_iso(),
                    trigger_reason=AssetTriggerReason(
                        discrepancy.get("reason", "DEPRECIATION_VARIANCE_EXCEEDS_THRESHOLD")
                    ),
                    affected_accounts=[GLAccountRef(
                        account_code=discrepancy.get("account", ""),
                        account_name=discrepancy.get("account_name", ""),
                    )],
                    discrepancy_detail=DiscrepancyDetail(
                        expected_balance=Decimal(str(detail.get("expected", 0))),
                        actual_balance=Decimal(str(detail.get("actual", 0))),
                        variance=Decimal(str(detail.get("variance", 0))),
                        variance_pct=detail.get("variance_pct", 0.0),
                        period=detail.get("period", ""),
                    ),
                    priority=Priority(discrepancy.get("priority", "HIGH")),
                ).model_dump()
                # Pass through test markers for self-heal path
                if discrepancy.get("_self_healable"):
                    inspection_request["_self_healable"] = True
                    inspection_request["_confidence"] = discrepancy.get("_confidence", 0.5)

    cp4_passed = len(asset_flags) == 0
    control_points.append(ControlPointResult(
        control_id="CP-004",
        description="Fixed-asset sub-ledger ties to GL control accounts",
        passed=cp4_passed,
        detail=f"Asset flags: {asset_flags}" if asset_flags else "No discrepancies",
    ))

    scan_result = ComplianceScanResult(
        scan_id=new_id(),
        timestamp=now_iso(),
        control_points=control_points,
        asset_flags=asset_flags,
        passed=all(cp.passed for cp in control_points),
    )

    envelope = make_envelope(
        source_agent=AgentId.COMPLIANCE_SPECIALIST,
        target_agent=AgentId.ASSET_WARDEN if asset_flags else AgentId.FINANCIAL_ANALYST,
        state_from=LedgerState.COMPLIANCE_SCAN,
        state_to=LedgerState.ASSET_INSPECTION if asset_flags else LedgerState.ANALYSIS,
        payload=scan_result.model_dump(),
        trace_id=trace_id,
    )

    result: dict = {
        "current_state": LedgerState.COMPLIANCE_SCAN,
        "compliance_result": scan_result.model_dump(),
        "asset_flags": asset_flags,
        "envelopes": [envelope],
    }
    if inspection_request:
        result["inspection_request"] = inspection_request
    return result
