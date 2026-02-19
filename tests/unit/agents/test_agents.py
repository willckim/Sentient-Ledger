"""Unit tests for Sentient Ledger agent stubs.

Each agent test verifies:
- Returns a dict with "current_state" and "envelopes" keys
- "envelopes" is a non-empty list
- Output state matches expectations
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from sentient_ledger.agents.audit_helpers import compute_proposal_checksum
from sentient_ledger.agents.process_manager import (
    audit_log_node,
    commit_node,
    error_quarantine_node,
    ingest_node,
    proposal_node,
    self_heal_node,
    sign_off_node,
)
from sentient_ledger.agents.compliance_specialist import compliance_specialist_node
from sentient_ledger.agents.asset_warden import asset_warden_node
from sentient_ledger.agents.financial_analyst import financial_analyst_node
from sentient_ledger.config import AUTHORITY_SLA_HOURS
from sentient_ledger.models.enums import (
    AuditEventType,
    AuthorityLevel,
    CommitResult,
    LedgerState,
    SignOffDecision,
)
from sentient_ledger.models.graph_state import create_initial_state


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def assert_agent_output_structure(result: dict) -> None:
    """Validate the common output structure all agent nodes must produce."""
    assert isinstance(result, dict), "Agent must return a dict"
    assert "current_state" in result, "Result must contain 'current_state'"
    assert "envelopes" in result, "Result must contain 'envelopes'"
    assert isinstance(result["envelopes"], list), "'envelopes' must be a list"
    assert len(result["envelopes"]) > 0, "'envelopes' must be non-empty"


def assert_envelope_structure(envelope: dict) -> None:
    """Validate that an envelope dict has the required fields."""
    required = {
        "envelope_id", "trace_id", "source_agent", "target_agent",
        "state_from", "state_to", "payload", "timestamp", "checksum",
        "schema_version",
    }
    missing = required - set(envelope.keys())
    assert not missing, f"Envelope missing fields: {missing}"
    assert envelope["checksum"] != "", "Envelope checksum should be populated"


# ---------------------------------------------------------------------------
# ingest_node
# ---------------------------------------------------------------------------

class TestIngestNode:
    def test_output_structure(self, base_state):
        result = ingest_node(base_state)
        assert_agent_output_structure(result)

    def test_current_state_is_ingest(self, base_state):
        result = ingest_node(base_state)
        assert result["current_state"] == LedgerState.INGEST

    def test_envelope_content(self, base_state):
        base_state["total_rows"] = 100
        base_state["malformed_pct"] = 0.5
        result = ingest_node(base_state)
        env = result["envelopes"][0]
        assert_envelope_structure(env)
        assert env["state_from"] == LedgerState.INGEST
        assert env["state_to"] == LedgerState.COMPLIANCE_SCAN

    def test_trace_id_propagated(self, base_state, trace_id):
        result = ingest_node(base_state)
        env = result["envelopes"][0]
        assert env["trace_id"] == trace_id


# ---------------------------------------------------------------------------
# compliance_specialist_node
# ---------------------------------------------------------------------------

class TestComplianceSpecialistNode:
    def test_output_structure_no_discrepancies(self, base_state, clean_tb_records):
        base_state["trial_balance_records"] = clean_tb_records
        result = compliance_specialist_node(base_state)
        assert_agent_output_structure(result)

    def test_current_state(self, base_state, clean_tb_records):
        base_state["trial_balance_records"] = clean_tb_records
        result = compliance_specialist_node(base_state)
        assert result["current_state"] == LedgerState.COMPLIANCE_SCAN

    def test_no_discrepancies_path(self, base_state, clean_tb_records):
        base_state["trial_balance_records"] = clean_tb_records
        result = compliance_specialist_node(base_state)
        assert result["asset_flags"] == []
        assert result["compliance_result"]["passed"] is True
        env = result["envelopes"][0]
        assert env["state_to"] == LedgerState.ANALYSIS

    def test_with_discrepancies(self, base_state, discrepancy_tb_records):
        base_state["trial_balance_records"] = discrepancy_tb_records
        result = compliance_specialist_node(base_state)
        assert_agent_output_structure(result)
        assert len(result["asset_flags"]) > 0
        env = result["envelopes"][0]
        assert env["state_to"] == LedgerState.ASSET_INSPECTION

    def test_discrepancy_produces_inspection_request(self, base_state, discrepancy_tb_records):
        base_state["trial_balance_records"] = discrepancy_tb_records
        result = compliance_specialist_node(base_state)
        assert "inspection_request" in result
        req = result["inspection_request"]
        assert req["trigger_reason"] == "DEPRECIATION_VARIANCE_EXCEEDS_THRESHOLD"

    def test_compliance_result_in_output(self, base_state, clean_tb_records):
        base_state["trial_balance_records"] = clean_tb_records
        result = compliance_specialist_node(base_state)
        cr = result["compliance_result"]
        assert "scan_id" in cr
        assert "control_points" in cr
        assert isinstance(cr["control_points"], list)

    def test_envelope_structure(self, base_state, clean_tb_records):
        base_state["trial_balance_records"] = clean_tb_records
        result = compliance_specialist_node(base_state)
        assert_envelope_structure(result["envelopes"][0])


# ---------------------------------------------------------------------------
# asset_warden_node
# ---------------------------------------------------------------------------

class TestAssetWardenNode:
    @pytest.fixture
    def state_with_inspection_request(self, base_state):
        base_state["inspection_request"] = {
            "request_id": "req-001",
            "trigger_reason": "DEPRECIATION_VARIANCE_EXCEEDS_THRESHOLD",
            "affected_accounts": [
                {"account_code": "1520", "account_name": "Accum Depreciation"}
            ],
            "discrepancy_detail": {
                "expected_balance": "33000",
                "actual_balance": "36000",
                "variance": "3000",
                "variance_pct": 0.09,
                "period": "2026-01",
            },
        }
        return base_state

    def test_output_structure(self, state_with_inspection_request):
        result = asset_warden_node(state_with_inspection_request)
        assert_agent_output_structure(result)

    def test_current_state(self, state_with_inspection_request):
        result = asset_warden_node(state_with_inspection_request)
        assert result["current_state"] == LedgerState.ASSET_INSPECTION

    def test_produces_inspection_report(self, state_with_inspection_request):
        result = asset_warden_node(state_with_inspection_request)
        report = result["inspection_report"]
        assert "report_id" in report
        assert "findings" in report
        assert len(report["findings"]) > 0

    def test_finding_asset_id(self, state_with_inspection_request):
        result = asset_warden_node(state_with_inspection_request)
        finding = result["inspection_report"]["findings"][0]
        assert finding["asset_id"] == "1520"

    def test_envelope_targets_analyst(self, state_with_inspection_request):
        result = asset_warden_node(state_with_inspection_request)
        env = result["envelopes"][0]
        assert_envelope_structure(env)
        assert env["state_from"] == LedgerState.ASSET_INSPECTION
        assert env["state_to"] == LedgerState.ANALYSIS

    def test_self_healable_marker(self, state_with_inspection_request):
        state_with_inspection_request["inspection_request"]["_self_healable"] = True
        state_with_inspection_request["inspection_request"]["_confidence"] = 0.99
        result = asset_warden_node(state_with_inspection_request)
        finding = result["inspection_report"]["findings"][0]
        assert finding["self_healable"] is True
        assert finding["confidence"] == 0.99


# ---------------------------------------------------------------------------
# financial_analyst_node
# ---------------------------------------------------------------------------

class TestFinancialAnalystNode:
    def test_output_structure_with_findings(self, base_state):
        base_state["inspection_report"] = {
            "findings": [
                {
                    "asset_id": "1520",
                    "error_type": "DEPRECIATION_VARIANCE_EXCEEDS_THRESHOLD",
                    "variance": "3000",
                }
            ]
        }
        result = financial_analyst_node(base_state)
        assert_agent_output_structure(result)

    def test_current_state(self, base_state):
        result = financial_analyst_node(base_state)
        assert result["current_state"] == LedgerState.ANALYSIS

    def test_with_adjustments(self, base_state):
        base_state["inspection_report"] = {
            "findings": [
                {
                    "asset_id": "1520",
                    "error_type": "DEPRECIATION_VARIANCE_EXCEEDS_THRESHOLD",
                    "variance": "3000",
                }
            ]
        }
        result = financial_analyst_node(base_state)
        assert len(result["proposed_adjustments"]) > 0
        env = result["envelopes"][0]
        assert env["state_to"] == LedgerState.PROPOSAL

    def test_clean_analysis_no_adjustments(self, base_state):
        """When no findings with variance, no adjustments are generated."""
        base_state["inspection_report"] = {"findings": []}
        result = financial_analyst_node(base_state)
        assert_agent_output_structure(result)
        assert result["proposed_adjustments"] == []
        env = result["envelopes"][0]
        assert env["state_to"] == LedgerState.AUDIT_LOG

    def test_analysis_result_structure(self, base_state):
        base_state["inspection_report"] = {
            "findings": [
                {"asset_id": "1520", "variance": "3000"}
            ]
        }
        result = financial_analyst_node(base_state)
        ar = result["analysis_result"]
        assert "findings_reviewed" in ar
        assert "adjustments" in ar
        assert ar["findings_reviewed"] == 1
        assert ar["adjustments"] == 1

    def test_envelope_structure(self, base_state):
        result = financial_analyst_node(base_state)
        assert_envelope_structure(result["envelopes"][0])

    def test_zero_variance_yields_no_adjustments(self, base_state):
        base_state["inspection_report"] = {
            "findings": [
                {"asset_id": "1520", "variance": "0"}
            ]
        }
        result = financial_analyst_node(base_state)
        assert result["proposed_adjustments"] == []


# ---------------------------------------------------------------------------
# proposal_node
# ---------------------------------------------------------------------------

class TestProposalNode:
    @pytest.fixture
    def state_with_adjustments(self, base_state):
        base_state["proposed_adjustments"] = [
            {
                "entry_id": "je-001",
                "debit_account": "1520",
                "debit_amount": "3000",
                "credit_account": "7200",
                "credit_amount": "3000",
                "memo": "Depreciation adjustment",
            }
        ]
        return base_state

    def test_output_structure(self, state_with_adjustments):
        result = proposal_node(state_with_adjustments)
        assert_agent_output_structure(result)

    def test_current_state(self, state_with_adjustments):
        result = proposal_node(state_with_adjustments)
        assert result["current_state"] == LedgerState.PROPOSAL

    def test_proposal_created(self, state_with_adjustments):
        result = proposal_node(state_with_adjustments)
        proposal = result["current_proposal"]
        assert "proposal_id" in proposal
        assert "journal_entries" in proposal
        assert len(proposal["journal_entries"]) == 1

    def test_total_impact_computed(self, state_with_adjustments):
        result = proposal_node(state_with_adjustments)
        proposal = result["current_proposal"]
        impact = proposal["total_impact"]
        assert Decimal(str(impact["absolute"])) == Decimal("3000")
        assert impact["accounts_affected"] == 1

    def test_authority_level_determined(self, state_with_adjustments):
        result = proposal_node(state_with_adjustments)
        proposal = result["current_proposal"]
        # 3000 <= 5000, so L1_STAFF
        assert proposal["required_approval"]["authority_level"] == AuthorityLevel.L1_STAFF

    def test_authority_l2_for_larger_amount(self, base_state):
        base_state["proposed_adjustments"] = [
            {
                "entry_id": "je-001",
                "debit_account": "1520",
                "debit_amount": "10000",
                "credit_account": "7200",
                "credit_amount": "10000",
                "memo": "Large adjustment",
            }
        ]
        result = proposal_node(base_state)
        proposal = result["current_proposal"]
        assert proposal["required_approval"]["authority_level"] == AuthorityLevel.L2_SENIOR

    def test_envelope_targets_sign_off(self, state_with_adjustments):
        result = proposal_node(state_with_adjustments)
        env = result["envelopes"][0]
        assert_envelope_structure(env)
        assert env["state_to"] == LedgerState.SIGN_OFF

    # --- P2: new tests ---

    def test_proposal_emits_created_audit_record(self, state_with_adjustments):
        result = proposal_node(state_with_adjustments)
        assert "audit_records" in result
        assert len(result["audit_records"]) == 1
        record = result["audit_records"][0]
        assert record["event_type"] == AuditEventType.CREATED

    def test_proposal_reasoning_chain_populated(self, state_with_adjustments):
        state_with_adjustments["inspection_request"] = {
            "trigger_reason": "DEPRECIATION_VARIANCE_EXCEEDS_THRESHOLD"
        }
        state_with_adjustments["inspection_report"] = {
            "findings": [{"asset_id": "1520", "confidence": 0.9}]
        }
        result = proposal_node(state_with_adjustments)
        chain = result["current_proposal"]["reasoning_chain"]
        assert chain is not None
        assert len(chain["logic_steps"]) >= 1
        assert chain["confidence"] > 0

    def test_proposal_reasoning_chain_empty_clean_path(self, state_with_adjustments):
        """On clean path (no inspection), reasoning chain has no logic steps."""
        result = proposal_node(state_with_adjustments)
        chain = result["current_proposal"]["reasoning_chain"]
        assert chain is not None
        assert len(chain["logic_steps"]) == 0

    def test_proposal_sla_deadline_computed(self, state_with_adjustments):
        result = proposal_node(state_with_adjustments)
        assert "sla_deadline" in result
        assert result["sla_deadline"] != ""
        # Deadline should be after created_at
        assert result["sla_deadline"] > result["proposal_created_at"]

    def test_proposal_history_on_rejection_cycle(self, state_with_adjustments):
        state_with_adjustments["sign_off_attempts"] = 1
        state_with_adjustments["current_proposal"] = {"proposal_id": "old-001", "old": True}
        result = proposal_node(state_with_adjustments)
        assert len(result["proposal_history"]) == 1
        assert result["proposal_history"][0]["proposal_id"] == "old-001"

    def test_proposal_history_empty_first_pass(self, state_with_adjustments):
        result = proposal_node(state_with_adjustments)
        assert result["proposal_history"] == []

    def test_proposal_checksum_in_audit_record(self, state_with_adjustments):
        result = proposal_node(state_with_adjustments)
        record = result["audit_records"][0]
        assert record["integrity"]["proposal_checksum"] != ""
        # Checksum should match recomputation
        expected = compute_proposal_checksum(result["current_proposal"])
        assert record["integrity"]["proposal_checksum"] == expected

    @pytest.mark.parametrize("amount,expected_level,expected_hours", [
        ("3000", AuthorityLevel.L1_STAFF, 4.0),
        ("10000", AuthorityLevel.L2_SENIOR, 8.0),
        ("100000", AuthorityLevel.L3_MANAGER, 24.0),
        ("600000", AuthorityLevel.L4_CONTROLLER, 48.0),
    ])
    def test_proposal_sla_hours_by_authority(self, base_state, amount, expected_level, expected_hours):
        base_state["proposed_adjustments"] = [
            {
                "entry_id": "je-001",
                "debit_account": "1520",
                "debit_amount": amount,
                "credit_account": "7200",
                "credit_amount": amount,
                "memo": "test",
            }
        ]
        result = proposal_node(base_state)
        proposal = result["current_proposal"]
        assert proposal["required_approval"]["authority_level"] == expected_level
        assert proposal["required_approval"]["sla_hours"] == expected_hours


# ---------------------------------------------------------------------------
# sign_off_node
# ---------------------------------------------------------------------------

class TestSignOffNode:
    def test_output_structure(self, base_state):
        result = sign_off_node(base_state)
        assert_agent_output_structure(result)

    def test_current_state(self, base_state):
        result = sign_off_node(base_state)
        assert result["current_state"] == LedgerState.SIGN_OFF

    def test_attempts_incremented(self, base_state):
        base_state["sign_off_attempts"] = 0
        result = sign_off_node(base_state)
        assert result["sign_off_attempts"] == 1

    def test_attempts_increment_from_nonzero(self, base_state):
        base_state["sign_off_attempts"] = 2
        result = sign_off_node(base_state)
        assert result["sign_off_attempts"] == 3

    def test_envelope_structure(self, base_state):
        result = sign_off_node(base_state)
        assert_envelope_structure(result["envelopes"][0])

    # --- P2: new tests ---

    def _state_with_proposal(self, base_state, decision=SignOffDecision.APPROVE):
        base_state["sign_off_decision"] = decision
        base_state["sign_off_authority"] = AuthorityLevel.L4_CONTROLLER
        base_state["current_proposal"] = {"proposal_id": "p-001", "amount": "3000"}
        now = datetime.now(timezone.utc)
        base_state["proposal_created_at"] = now.isoformat()
        base_state["sla_deadline"] = (now + timedelta(hours=48)).isoformat()
        base_state["sign_off_timestamp"] = (now + timedelta(hours=1)).isoformat()
        return base_state

    def test_sign_off_emits_approved_audit_record(self, base_state):
        state = self._state_with_proposal(base_state, SignOffDecision.APPROVE)
        result = sign_off_node(state)
        assert len(result["audit_records"]) == 1
        assert result["audit_records"][0]["event_type"] == AuditEventType.APPROVED

    def test_sign_off_emits_rejected_audit_record(self, base_state):
        state = self._state_with_proposal(base_state, SignOffDecision.REJECT)
        state["sign_off_reason"] = "Needs more detail"
        result = sign_off_node(state)
        assert result["audit_records"][0]["event_type"] == AuditEventType.REJECTED

    def test_sign_off_emits_escalated_audit_record(self, base_state):
        state = self._state_with_proposal(base_state, SignOffDecision.ESCALATE)
        result = sign_off_node(state)
        assert result["audit_records"][0]["event_type"] == AuditEventType.ESCALATED

    def test_sign_off_audit_has_human_actor(self, base_state):
        state = self._state_with_proposal(base_state)
        result = sign_off_node(state)
        actor = result["audit_records"][0]["actor"]
        assert actor["type"] == "HUMAN"

    def test_sign_off_captures_reviewer_notes(self, base_state):
        state = self._state_with_proposal(base_state)
        state["sign_off_reviewer_notes"] = "Looks good to me"
        result = sign_off_node(state)
        detail = result["audit_records"][0]["detail"]
        assert detail["reviewer_notes"] == "Looks good to me"

    def test_sign_off_captures_rejection_reason(self, base_state):
        state = self._state_with_proposal(base_state, SignOffDecision.REJECT)
        state["sign_off_reason"] = "Amounts are incorrect"
        result = sign_off_node(state)
        detail = result["audit_records"][0]["detail"]
        assert detail["rejection_reason"] == "Amounts are incorrect"

    def test_sign_off_time_in_review_computed(self, base_state):
        state = self._state_with_proposal(base_state)
        result = sign_off_node(state)
        detail = result["audit_records"][0]["detail"]
        assert detail["time_in_review_ms"] > 0

    def test_sign_off_sla_expiry_auto_escalates(self, base_state):
        state = self._state_with_proposal(base_state, SignOffDecision.APPROVE)
        now = datetime.now(timezone.utc)
        state["proposal_created_at"] = now.isoformat()
        state["sla_deadline"] = (now + timedelta(hours=4)).isoformat()
        # Sign-off happens AFTER SLA deadline
        state["sign_off_timestamp"] = (now + timedelta(hours=5)).isoformat()
        result = sign_off_node(state)
        assert result["audit_records"][0]["event_type"] == AuditEventType.ESCALATED

    def test_sign_off_auto_approve_second_rejection_audit(self, base_state):
        state = self._state_with_proposal(base_state, SignOffDecision.REJECT)
        state["sign_off_attempts"] = 1  # will become 2
        result = sign_off_node(state)
        # Auto-approved on 2nd rejection
        assert result["audit_records"][0]["event_type"] == AuditEventType.APPROVED

    def test_sign_off_proposal_checksum_in_audit(self, base_state):
        state = self._state_with_proposal(base_state)
        result = sign_off_node(state)
        checksum = result["audit_records"][0]["integrity"]["proposal_checksum"]
        assert checksum != ""
        expected = compute_proposal_checksum(state["current_proposal"])
        assert checksum == expected


# ---------------------------------------------------------------------------
# commit_node
# ---------------------------------------------------------------------------

class TestCommitNode:
    def test_output_structure(self, base_state):
        result = commit_node(base_state)
        assert_agent_output_structure(result)

    def test_current_state(self, base_state):
        result = commit_node(base_state)
        assert result["current_state"] == LedgerState.COMMIT

    def test_ack_routes_to_audit_log(self, base_state):
        base_state["commit_result"] = CommitResult.ACK
        result = commit_node(base_state)
        env = result["envelopes"][0]
        assert env["state_to"] == LedgerState.AUDIT_LOG

    def test_nack_routes_to_error_quarantine(self, base_state):
        base_state["commit_result"] = CommitResult.NACK
        result = commit_node(base_state)
        env = result["envelopes"][0]
        assert env["state_to"] == LedgerState.ERROR_QUARANTINE

    def test_default_ack(self, base_state):
        """Without commit_result set, defaults to ACK."""
        result = commit_node(base_state)
        env = result["envelopes"][0]
        assert env["state_to"] == LedgerState.AUDIT_LOG

    def test_envelope_structure(self, base_state):
        result = commit_node(base_state)
        assert_envelope_structure(result["envelopes"][0])


# ---------------------------------------------------------------------------
# audit_log_node
# ---------------------------------------------------------------------------

class TestAuditLogNode:
    def test_output_structure(self, base_state):
        result = audit_log_node(base_state)
        assert_agent_output_structure(result)

    def test_current_state(self, base_state):
        result = audit_log_node(base_state)
        assert result["current_state"] == LedgerState.AUDIT_LOG

    def test_audit_record_created(self, base_state):
        result = audit_log_node(base_state)
        assert "audit_records" in result
        assert len(result["audit_records"]) == 1
        record = result["audit_records"][0]
        assert "record_id" in record
        assert record["event_type"] == "COMMITTED"

    def test_hash_chain_initial(self, base_state):
        """First record should have empty previous_record_hash."""
        result = audit_log_node(base_state)
        record = result["audit_records"][0]
        assert record["integrity"]["previous_record_hash"] == ""
        assert record["integrity"]["record_hash"] != ""

    def test_hash_chain_with_previous_record(self, base_state):
        """Should link to the previous record's hash."""
        base_state["audit_records"] = [
            {
                "record_id": "prev-001",
                "integrity": {"record_hash": "abc123def456"},
            }
        ]
        result = audit_log_node(base_state)
        record = result["audit_records"][0]
        assert record["integrity"]["previous_record_hash"] == "abc123def456"

    def test_proposal_id_from_state(self, base_state):
        base_state["current_proposal"] = {"proposal_id": "prop-xyz"}
        result = audit_log_node(base_state)
        record = result["audit_records"][0]
        assert record["proposal_id"] == "prop-xyz"

    def test_envelope_structure(self, base_state):
        result = audit_log_node(base_state)
        assert_envelope_structure(result["envelopes"][0])

    # --- P2: new tests ---

    def test_audit_log_chains_from_prior_lifecycle_records(self, base_state):
        """audit_log_node links to existing records from proposal/sign_off."""
        base_state["audit_records"] = [
            {"record_id": "r-001", "event_type": "CREATED", "integrity": {"record_hash": "hash1"}},
            {"record_id": "r-002", "event_type": "APPROVED", "integrity": {"record_hash": "hash2"}},
        ]
        result = audit_log_node(base_state)
        record = result["audit_records"][0]
        assert record["integrity"]["previous_record_hash"] == "hash2"

    def test_audit_log_proposal_checksum(self, base_state):
        base_state["current_proposal"] = {"proposal_id": "p-001", "amount": "3000"}
        result = audit_log_node(base_state)
        record = result["audit_records"][0]
        assert record["integrity"]["proposal_checksum"] != ""
        expected = compute_proposal_checksum(base_state["current_proposal"])
        assert record["integrity"]["proposal_checksum"] == expected


# ---------------------------------------------------------------------------
# error_quarantine_node
# ---------------------------------------------------------------------------

class TestErrorQuarantineNode:
    def test_output_structure(self, base_state):
        result = error_quarantine_node(base_state)
        assert_agent_output_structure(result)

    def test_current_state(self, base_state):
        result = error_quarantine_node(base_state)
        assert result["current_state"] == LedgerState.ERROR_QUARANTINE

    def test_error_detail_in_envelope(self, base_state):
        base_state["error_detail"] = "Something went wrong"
        result = error_quarantine_node(base_state)
        env = result["envelopes"][0]
        assert env["payload"]["error_detail"] == "Something went wrong"

    def test_default_error_detail(self, base_state):
        result = error_quarantine_node(base_state)
        env = result["envelopes"][0]
        assert env["payload"]["error_detail"] == ""

    def test_envelope_structure(self, base_state):
        result = error_quarantine_node(base_state)
        assert_envelope_structure(result["envelopes"][0])


# ---------------------------------------------------------------------------
# self_heal_node
# ---------------------------------------------------------------------------

class TestSelfHealNode:
    @pytest.fixture
    def state_with_healable_finding(self, base_state):
        base_state["inspection_report"] = {
            "findings": [
                {
                    "finding_id": "f-001",
                    "asset_id": "1520",
                    "self_healable": True,
                    "pattern_id": "AW-001",
                    "variance": "3000",
                }
            ]
        }
        return base_state

    def test_output_structure(self, state_with_healable_finding):
        result = self_heal_node(state_with_healable_finding)
        assert_agent_output_structure(result)

    def test_current_state(self, state_with_healable_finding):
        result = self_heal_node(state_with_healable_finding)
        assert result["current_state"] == LedgerState.SELF_HEAL

    def test_correction_generated(self, state_with_healable_finding):
        result = self_heal_node(state_with_healable_finding)
        correction = result["self_heal_correction"]
        assert correction is not None
        assert correction["pattern_id"] == "AW-001"
        assert correction["finding_id"] == "f-001"
        assert correction["amount"] == "3000"

    def test_proposed_adjustments_populated(self, state_with_healable_finding):
        result = self_heal_node(state_with_healable_finding)
        adjustments = result["proposed_adjustments"]
        assert len(adjustments) == 1
        adj = adjustments[0]
        assert "entry_id" in adj
        assert adj["debit_account"] == "1520"
        assert adj["credit_account"] == "correction-offset"

    def test_no_healable_finding_fallback(self, base_state):
        base_state["inspection_report"] = {
            "findings": [
                {
                    "finding_id": "f-002",
                    "asset_id": "1520",
                    "self_healable": False,
                    "variance": "1000",
                }
            ]
        }
        result = self_heal_node(base_state)
        assert_agent_output_structure(result)
        correction = result["self_heal_correction"]
        assert correction["pattern_id"] == "UNKNOWN"

    def test_envelope_targets_proposal(self, state_with_healable_finding):
        result = self_heal_node(state_with_healable_finding)
        env = result["envelopes"][0]
        assert_envelope_structure(env)
        assert env["state_from"] == LedgerState.SELF_HEAL
        assert env["state_to"] == LedgerState.PROPOSAL

    def test_envelope_structure(self, state_with_healable_finding):
        result = self_heal_node(state_with_healable_finding)
        assert_envelope_structure(result["envelopes"][0])
