"""Unit tests for Sentient Ledger Pydantic models, enums, and factories."""

import hashlib
import json
import uuid
from decimal import Decimal

import pytest

from sentient_ledger.config import SCHEMA_VERSION
from sentient_ledger.models.enums import (
    AUTHORITY_RANK,
    AccountCategory,
    ActorType,
    AgentId,
    AssetStatus,
    AssetTriggerReason,
    AuditEventType,
    AuthorityLevel,
    CommitResult,
    DepreciationConvention,
    DepreciationMethod,
    LedgerState,
    Priority,
    ProposalStatus,
    SelfHealPatternId,
    SignOffDecision,
)
from sentient_ledger.models.envelope import StateEnvelope
from sentient_ledger.models.trial_balance import (
    AccountInfo,
    Balances,
    CanonicalTrialBalance,
    CurrencyInfo,
    Dimensions,
    IntegrityInfo,
    PeriodInfo,
)
from sentient_ledger.models.asset import (
    Acquisition,
    AssetFinding,
    AssetIdentity,
    AssetInspectionReport,
    AssetInspectionRequest,
    AssetIntegrity,
    CanonicalAssetRecord,
    CurrentState,
    DiscrepancyDetail,
    GLAccountRef,
)
from sentient_ledger.models.compliance import (
    ComplianceScanResult,
    ControlPointResult,
)
from sentient_ledger.models.proposal import (
    AdjustmentProposal,
    JournalEntry,
    ReasoningStep,
    RequiredApproval,
    TotalImpact,
)
from sentient_ledger.models.audit import (
    AuditActor,
    AuditDetail,
    AuditIntegrity,
    AuditRecord,
)
from sentient_ledger.models.graph_state import ReconciliationState, create_initial_state


# ---------------------------------------------------------------------------
# Enum membership tests
# ---------------------------------------------------------------------------

class TestLedgerStateEnum:
    def test_all_members(self):
        expected = {
            "INGEST", "COMPLIANCE_SCAN", "ASSET_INSPECTION", "ANALYSIS",
            "PROPOSAL", "SIGN_OFF", "COMMIT", "AUDIT_LOG",
            "ERROR_QUARANTINE", "SELF_HEAL",
        }
        assert {e.value for e in LedgerState} == expected

    def test_string_value(self):
        assert LedgerState.INGEST == "INGEST"
        assert isinstance(LedgerState.INGEST, str)


class TestAgentIdEnum:
    def test_all_members(self):
        expected = {
            "COMPLIANCE_SPECIALIST", "ASSET_WARDEN",
            "FINANCIAL_ANALYST", "PROCESS_MANAGER", "SYSTEM",
        }
        assert {e.value for e in AgentId} == expected


class TestAssetTriggerReasonEnum:
    def test_all_members(self):
        expected = {
            "DEPRECIATION_VARIANCE_EXCEEDS_THRESHOLD",
            "MISSING_DEPRECIATION_ENTRY",
            "DISPOSAL_WITHOUT_RETIREMENT",
            "IMPAIRMENT_INDICATOR_DETECTED",
            "USEFUL_LIFE_MISMATCH",
            "RECLASSIFICATION_ANOMALY",
        }
        assert {e.value for e in AssetTriggerReason} == expected


class TestAuthorityLevelEnum:
    def test_all_members(self):
        expected = {"L1_STAFF", "L2_SENIOR", "L3_MANAGER", "L4_CONTROLLER"}
        assert {e.value for e in AuthorityLevel} == expected

    def test_authority_rank_ordering(self):
        assert AUTHORITY_RANK[AuthorityLevel.L1_STAFF] < AUTHORITY_RANK[AuthorityLevel.L2_SENIOR]
        assert AUTHORITY_RANK[AuthorityLevel.L2_SENIOR] < AUTHORITY_RANK[AuthorityLevel.L3_MANAGER]
        assert AUTHORITY_RANK[AuthorityLevel.L3_MANAGER] < AUTHORITY_RANK[AuthorityLevel.L4_CONTROLLER]


class TestAccountCategoryEnum:
    def test_all_members(self):
        expected = {"ASSET", "LIABILITY", "EQUITY", "REVENUE", "EXPENSE"}
        assert {e.value for e in AccountCategory} == expected


class TestDepreciationMethodEnum:
    def test_all_members(self):
        expected = {
            "STRAIGHT_LINE", "DOUBLE_DECLINING", "SUM_OF_YEARS",
            "UNITS_OF_PRODUCTION", "MACRS",
        }
        assert {e.value for e in DepreciationMethod} == expected


class TestDepreciationConventionEnum:
    def test_all_members(self):
        expected = {
            "FULL_MONTH", "HALF_MONTH", "MID_MONTH",
            "HALF_YEAR", "MID_QUARTER",
        }
        assert {e.value for e in DepreciationConvention} == expected


class TestAssetStatusEnum:
    def test_all_members(self):
        expected = {"ACTIVE", "FULLY_DEPRECIATED", "DISPOSED", "IMPAIRED", "SUSPENDED"}
        assert {e.value for e in AssetStatus} == expected


class TestPriorityEnum:
    def test_all_members(self):
        expected = {"CRITICAL", "HIGH", "MEDIUM"}
        assert {e.value for e in Priority} == expected


class TestProposalStatusEnum:
    def test_all_members(self):
        expected = {"PENDING_REVIEW", "APPROVED", "REJECTED", "ESCALATED", "EXPIRED"}
        assert {e.value for e in ProposalStatus} == expected


class TestAuditEventTypeEnum:
    def test_all_members(self):
        expected = {
            "CREATED", "VIEWED", "APPROVED", "REJECTED",
            "ESCALATED", "EXPIRED", "COMMITTED",
        }
        assert {e.value for e in AuditEventType} == expected


class TestActorTypeEnum:
    def test_all_members(self):
        expected = {"AGENT", "HUMAN"}
        assert {e.value for e in ActorType} == expected


class TestSignOffDecisionEnum:
    def test_all_members(self):
        expected = {"APPROVE", "REJECT", "ESCALATE"}
        assert {e.value for e in SignOffDecision} == expected


class TestCommitResultEnum:
    def test_all_members(self):
        expected = {"ACK", "NACK"}
        assert {e.value for e in CommitResult} == expected


class TestSelfHealPatternIdEnum:
    def test_all_members(self):
        expected = {"AW-001", "AW-002", "AW-003", "AW-004", "AW-005"}
        assert {e.value for e in SelfHealPatternId} == expected


# ---------------------------------------------------------------------------
# Pydantic model construction & validation tests
# ---------------------------------------------------------------------------

class TestCanonicalTrialBalance:
    @pytest.fixture
    def trial_balance(self):
        return CanonicalTrialBalance(
            record_id="tb-001",
            account=AccountInfo(
                code="1000",
                name="Cash",
                category=AccountCategory.ASSET,
            ),
            dimensions=Dimensions(business_unit="BU-01"),
            balances=Balances(
                opening=Decimal("10000"),
                debits=Decimal("5000"),
                credits=Decimal("3000"),
                closing=Decimal("12000"),
            ),
            period=PeriodInfo(
                fiscal_year=2026,
                fiscal_period=1,
                calendar_month="2026-01",
            ),
        )

    def test_construction(self, trial_balance):
        assert trial_balance.record_id == "tb-001"
        assert trial_balance.account.code == "1000"
        assert trial_balance.account.category == AccountCategory.ASSET
        assert trial_balance.balances.opening == Decimal("10000")
        assert trial_balance.period.fiscal_year == 2026

    def test_defaults(self, trial_balance):
        assert trial_balance.source == "DYNAMICS_365"
        assert trial_balance.ingestion_id == ""
        assert trial_balance.currency.transaction == "USD"
        assert trial_balance.integrity.balance_verified is False

    def test_invalid_category_rejected(self):
        with pytest.raises(Exception):
            AccountInfo(code="1000", name="Cash", category="INVALID_CATEGORY")

    def test_round_trip(self, trial_balance):
        data = trial_balance.model_dump()
        restored = CanonicalTrialBalance.model_validate(data)
        assert restored.record_id == trial_balance.record_id
        assert restored.balances.closing == trial_balance.balances.closing
        assert restored.account.category == trial_balance.account.category


class TestAssetInspectionRequest:
    @pytest.fixture
    def inspection_request(self):
        return AssetInspectionRequest(
            request_id="req-001",
            timestamp="2026-01-15T10:00:00Z",
            trigger_reason=AssetTriggerReason.DEPRECIATION_VARIANCE_EXCEEDS_THRESHOLD,
            affected_accounts=[
                GLAccountRef(account_code="1520", account_name="Accum Depreciation")
            ],
            discrepancy_detail=DiscrepancyDetail(
                expected_balance=Decimal("33000"),
                actual_balance=Decimal("36000"),
                variance=Decimal("3000"),
                variance_pct=0.09,
                period="2026-01",
            ),
            priority=Priority.HIGH,
        )

    def test_construction(self, inspection_request):
        assert inspection_request.request_id == "req-001"
        assert inspection_request.trigger_reason == AssetTriggerReason.DEPRECIATION_VARIANCE_EXCEEDS_THRESHOLD
        assert len(inspection_request.affected_accounts) == 1
        assert inspection_request.priority == Priority.HIGH

    def test_discrepancy_detail_values(self, inspection_request):
        d = inspection_request.discrepancy_detail
        assert d.expected_balance == Decimal("33000")
        assert d.actual_balance == Decimal("36000")
        assert d.variance == Decimal("3000")

    def test_round_trip(self, inspection_request):
        data = inspection_request.model_dump()
        restored = AssetInspectionRequest.model_validate(data)
        assert restored.request_id == inspection_request.request_id
        assert restored.discrepancy_detail.variance == inspection_request.discrepancy_detail.variance


class TestComplianceScanResult:
    @pytest.fixture
    def scan_result(self):
        return ComplianceScanResult(
            scan_id="scan-001",
            timestamp="2026-01-15T10:00:00Z",
            control_points=[
                ControlPointResult(
                    control_id="CP-001",
                    description="Trial balance foots",
                    passed=True,
                    detail="OK",
                ),
                ControlPointResult(
                    control_id="CP-004",
                    description="Asset sub-ledger ties",
                    passed=False,
                    detail="Mismatch found",
                ),
            ],
            asset_flags=["ASSET_DISCREPANCY:1520"],
            passed=False,
        )

    def test_construction(self, scan_result):
        assert scan_result.scan_id == "scan-001"
        assert len(scan_result.control_points) == 2
        assert scan_result.passed is False
        assert "ASSET_DISCREPANCY:1520" in scan_result.asset_flags

    def test_control_point_details(self, scan_result):
        cp1, cp4 = scan_result.control_points
        assert cp1.passed is True
        assert cp4.passed is False

    def test_round_trip(self, scan_result):
        data = scan_result.model_dump()
        restored = ComplianceScanResult.model_validate(data)
        assert restored.scan_id == scan_result.scan_id
        assert len(restored.control_points) == 2


class TestAdjustmentProposal:
    @pytest.fixture
    def proposal(self):
        return AdjustmentProposal(
            proposal_id="prop-001",
            trace_id="trace-001",
            created_at="2026-01-15T10:00:00Z",
            created_by=AgentId.FINANCIAL_ANALYST,
            journal_entries=[
                JournalEntry(
                    entry_id="je-001",
                    debit_account="1520",
                    debit_amount=Decimal("3000"),
                    credit_account="7200",
                    credit_amount=Decimal("3000"),
                    memo="Depreciation correction",
                ),
            ],
            total_impact=TotalImpact(
                absolute=Decimal("3000"),
                accounts_affected=2,
            ),
            reasoning_steps=[
                ReasoningStep(
                    step_number=1,
                    action="Identified variance",
                    output_summary="3000 variance in accumulated depreciation",
                ),
            ],
            confidence=0.95,
            required_approval=RequiredApproval(
                authority_level=AuthorityLevel.L1_STAFF,
            ),
        )

    def test_construction(self, proposal):
        assert proposal.proposal_id == "prop-001"
        assert proposal.created_by == AgentId.FINANCIAL_ANALYST
        assert proposal.status == ProposalStatus.PENDING_REVIEW
        assert proposal.confidence == 0.95

    def test_journal_entries(self, proposal):
        assert len(proposal.journal_entries) == 1
        je = proposal.journal_entries[0]
        assert je.debit_amount == Decimal("3000")
        assert je.credit_amount == Decimal("3000")

    def test_total_impact(self, proposal):
        assert proposal.total_impact.absolute == Decimal("3000")
        assert proposal.total_impact.accounts_affected == 2

    def test_default_status(self, proposal):
        assert proposal.status == ProposalStatus.PENDING_REVIEW

    def test_rejection_context_none_by_default(self, proposal):
        assert proposal.rejection_context is None

    def test_round_trip(self, proposal):
        data = proposal.model_dump()
        restored = AdjustmentProposal.model_validate(data)
        assert restored.proposal_id == proposal.proposal_id
        assert restored.total_impact.absolute == proposal.total_impact.absolute
        assert restored.journal_entries[0].debit_amount == proposal.journal_entries[0].debit_amount


class TestAuditRecord:
    @pytest.fixture
    def audit_record(self):
        return AuditRecord(
            record_id="audit-001",
            trace_id="trace-001",
            proposal_id="prop-001",
            event_type=AuditEventType.COMMITTED,
            actor=AuditActor(
                type=ActorType.AGENT,
                id="PROCESS_MANAGER",
                role="system",
                authority_level=AuthorityLevel.L4_CONTROLLER,
            ),
            timestamp="2026-01-15T12:00:00Z",
            detail=AuditDetail(
                reasoning_snapshot="Reconciliation complete",
            ),
            integrity=AuditIntegrity(
                previous_record_hash="abc123",
            ),
        )

    def test_construction(self, audit_record):
        assert audit_record.record_id == "audit-001"
        assert audit_record.event_type == AuditEventType.COMMITTED
        assert audit_record.actor.type == ActorType.AGENT

    def test_compute_hash_deterministic(self, audit_record):
        h1 = audit_record.compute_hash()
        h2 = audit_record.compute_hash()
        assert h1 == h2
        assert len(h1) == 64  # SHA-256 hex digest length

    def test_compute_hash_excludes_integrity(self, audit_record):
        """compute_hash excludes the integrity field so changing it does not change the hash."""
        h_before = audit_record.compute_hash()
        audit_record.integrity.record_hash = "changed-value"
        h_after = audit_record.compute_hash()
        assert h_before == h_after

    def test_compute_hash_changes_with_data(self, audit_record):
        h_original = audit_record.compute_hash()
        audit_record.proposal_id = "prop-999"
        h_modified = audit_record.compute_hash()
        assert h_original != h_modified

    def test_hash_matches_manual_sha256(self, audit_record):
        data = audit_record.model_dump(exclude={"integrity"})
        raw = json.dumps(data, sort_keys=True, default=str)
        expected = hashlib.sha256(raw.encode()).hexdigest()
        assert audit_record.compute_hash() == expected

    def test_round_trip(self, audit_record):
        data = audit_record.model_dump()
        restored = AuditRecord.model_validate(data)
        assert restored.record_id == audit_record.record_id
        assert restored.compute_hash() == audit_record.compute_hash()


# ---------------------------------------------------------------------------
# StateEnvelope checksum tests
# ---------------------------------------------------------------------------

class TestStateEnvelope:
    @pytest.fixture
    def envelope(self):
        return StateEnvelope(
            envelope_id="env-001",
            trace_id="trace-001",
            source_agent=AgentId.SYSTEM,
            target_agent=AgentId.COMPLIANCE_SPECIALIST,
            state_from=LedgerState.INGEST,
            state_to=LedgerState.COMPLIANCE_SCAN,
            payload={"total_rows": 100, "malformed_pct": 0.5},
            timestamp="2026-01-15T10:00:00Z",
        )

    def test_construction(self, envelope):
        assert envelope.envelope_id == "env-001"
        assert envelope.source_agent == AgentId.SYSTEM
        assert envelope.schema_version == SCHEMA_VERSION

    def test_checksum_initially_empty(self, envelope):
        assert envelope.checksum == ""

    def test_compute_checksum_deterministic(self, envelope):
        c1 = envelope.compute_checksum()
        c2 = envelope.compute_checksum()
        assert c1 == c2
        assert len(c1) == 64

    def test_with_checksum_populates_field(self, envelope):
        result = envelope.with_checksum()
        assert result.checksum != ""
        assert result.checksum == envelope.compute_checksum()
        assert result is envelope  # mutates in place and returns self

    def test_checksum_changes_with_payload(self, envelope):
        c_original = envelope.compute_checksum()
        envelope.payload = {"different": "data"}
        c_modified = envelope.compute_checksum()
        assert c_original != c_modified

    def test_checksum_matches_manual_sha256(self, envelope):
        raw = json.dumps(envelope.payload, sort_keys=True, default=str)
        expected = hashlib.sha256(raw.encode()).hexdigest()
        assert envelope.compute_checksum() == expected

    def test_parent_envelope_id_defaults_to_none(self, envelope):
        assert envelope.parent_envelope_id is None

    def test_round_trip(self, envelope):
        envelope.with_checksum()
        data = envelope.model_dump()
        restored = StateEnvelope.model_validate(data)
        assert restored.envelope_id == envelope.envelope_id
        assert restored.checksum == envelope.checksum
        assert restored.payload == envelope.payload


# ---------------------------------------------------------------------------
# create_initial_state factory tests
# ---------------------------------------------------------------------------

class TestCreateInitialState:
    def test_returns_typed_dict(self):
        state = create_initial_state("test-trace")
        assert isinstance(state, dict)

    def test_trace_id_set(self):
        state = create_initial_state("my-trace-123")
        assert state["trace_id"] == "my-trace-123"

    def test_initial_ledger_state(self):
        state = create_initial_state("t")
        assert state["current_state"] == LedgerState.INGEST

    def test_empty_collections(self):
        state = create_initial_state("t")
        assert state["envelopes"] == []
        assert state["trial_balance_records"] == []
        assert state["asset_flags"] == []
        assert state["proposed_adjustments"] == []
        assert state["audit_records"] == []

    def test_numeric_defaults(self):
        state = create_initial_state("t")
        assert state["malformed_pct"] == 0.0
        assert state["total_rows"] == 0
        assert state["malformed_rows"] == 0
        assert state["sign_off_attempts"] == 0

    def test_error_detail_empty(self):
        state = create_initial_state("t")
        assert state["error_detail"] == ""

    def test_different_trace_ids_produce_different_states(self):
        s1 = create_initial_state("trace-A")
        s2 = create_initial_state("trace-B")
        assert s1["trace_id"] != s2["trace_id"]
        # But structure is the same
        assert set(s1.keys()) == set(s2.keys())
