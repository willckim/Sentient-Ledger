"""Unit tests for Sentient Ledger guard functions.

Each guard is tested for both its True and False paths.
"""

from decimal import Decimal

import pytest

from sentient_ledger.config import (
    MALFORMED_ROW_THRESHOLD_PCT,
    SELF_HEAL_CONFIDENCE_THRESHOLD,
)
from sentient_ledger.guards.ingest_guards import (
    malformed_exceeds_threshold,
    schema_validation_passes,
)
from sentient_ledger.guards.compliance_guards import (
    asset_discrepancy_detected,
    no_asset_discrepancies,
)
from sentient_ledger.guards.asset_guards import (
    inspection_complete,
    known_error_pattern_matched,
)
from sentient_ledger.guards.analysis_guards import (
    adjustments_identified,
    clean_analysis,
)
from sentient_ledger.guards.signoff_guards import (
    human_approves,
    human_escalates,
    human_rejects,
)
from sentient_ledger.guards.commit_guards import (
    mutation_fails,
    mutation_succeeds,
)
from sentient_ledger.guards.selfheal_guards import correction_generated
from sentient_ledger.models.enums import (
    AuthorityLevel,
    CommitResult,
    SignOffDecision,
)
from sentient_ledger.models.graph_state import create_initial_state


# ---------------------------------------------------------------------------
# Ingest guards
# ---------------------------------------------------------------------------

class TestSchemaValidationPasses:
    def test_passes_when_below_threshold(self):
        state = create_initial_state("t")
        state["malformed_pct"] = 0.5
        assert schema_validation_passes(state) is True

    def test_passes_when_at_threshold(self):
        state = create_initial_state("t")
        state["malformed_pct"] = MALFORMED_ROW_THRESHOLD_PCT
        assert schema_validation_passes(state) is True

    def test_fails_when_above_threshold(self):
        state = create_initial_state("t")
        state["malformed_pct"] = MALFORMED_ROW_THRESHOLD_PCT + 0.1
        assert schema_validation_passes(state) is False

    def test_passes_when_zero(self):
        state = create_initial_state("t")
        state["malformed_pct"] = 0.0
        assert schema_validation_passes(state) is True


class TestMalformedExceedsThreshold:
    def test_true_when_above_threshold(self):
        state = create_initial_state("t")
        state["malformed_pct"] = MALFORMED_ROW_THRESHOLD_PCT + 0.5
        assert malformed_exceeds_threshold(state) is True

    def test_false_when_below_threshold(self):
        state = create_initial_state("t")
        state["malformed_pct"] = 0.5
        assert malformed_exceeds_threshold(state) is False

    def test_false_when_at_threshold(self):
        state = create_initial_state("t")
        state["malformed_pct"] = MALFORMED_ROW_THRESHOLD_PCT
        assert malformed_exceeds_threshold(state) is False

    def test_inverse_of_schema_validation(self):
        """The two ingest guards should be logical inverses."""
        state = create_initial_state("t")
        for pct in [0.0, 0.5, 1.0, 1.5, 5.0]:
            state["malformed_pct"] = pct
            assert schema_validation_passes(state) != malformed_exceeds_threshold(state)


# ---------------------------------------------------------------------------
# Compliance guards
# ---------------------------------------------------------------------------

class TestAssetDiscrepancyDetected:
    def test_true_when_flags_present(self):
        state = create_initial_state("t")
        state["asset_flags"] = ["ASSET_DISCREPANCY:1520"]
        assert asset_discrepancy_detected(state) is True

    def test_false_when_no_flags(self):
        state = create_initial_state("t")
        state["asset_flags"] = []
        assert asset_discrepancy_detected(state) is False

    def test_true_with_multiple_flags(self):
        state = create_initial_state("t")
        state["asset_flags"] = ["FLAG_A", "FLAG_B", "FLAG_C"]
        assert asset_discrepancy_detected(state) is True


class TestNoAssetDiscrepancies:
    def test_true_when_no_flags(self):
        state = create_initial_state("t")
        state["asset_flags"] = []
        assert no_asset_discrepancies(state) is True

    def test_false_when_flags_present(self):
        state = create_initial_state("t")
        state["asset_flags"] = ["DISCREPANCY"]
        assert no_asset_discrepancies(state) is False

    def test_inverse_of_asset_discrepancy_detected(self):
        state = create_initial_state("t")
        for flags in [[], ["A"], ["A", "B"]]:
            state["asset_flags"] = flags
            assert no_asset_discrepancies(state) != asset_discrepancy_detected(state)


# ---------------------------------------------------------------------------
# Asset guards
# ---------------------------------------------------------------------------

class TestKnownErrorPatternMatched:
    def test_true_when_self_healable_high_confidence(self):
        state = create_initial_state("t")
        state["inspection_report"] = {
            "findings": [
                {
                    "self_healable": True,
                    "confidence": SELF_HEAL_CONFIDENCE_THRESHOLD,
                }
            ]
        }
        assert known_error_pattern_matched(state) is True

    def test_true_when_confidence_above_threshold(self):
        state = create_initial_state("t")
        state["inspection_report"] = {
            "findings": [
                {
                    "self_healable": True,
                    "confidence": 0.99,
                }
            ]
        }
        assert known_error_pattern_matched(state) is True

    def test_false_when_not_self_healable(self):
        state = create_initial_state("t")
        state["inspection_report"] = {
            "findings": [
                {
                    "self_healable": False,
                    "confidence": 0.99,
                }
            ]
        }
        assert known_error_pattern_matched(state) is False

    def test_false_when_confidence_below_threshold(self):
        state = create_initial_state("t")
        state["inspection_report"] = {
            "findings": [
                {
                    "self_healable": True,
                    "confidence": SELF_HEAL_CONFIDENCE_THRESHOLD - 0.01,
                }
            ]
        }
        assert known_error_pattern_matched(state) is False

    def test_false_when_no_findings(self):
        state = create_initial_state("t")
        state["inspection_report"] = {"findings": []}
        assert known_error_pattern_matched(state) is False

    def test_false_when_no_report(self):
        state = create_initial_state("t")
        assert known_error_pattern_matched(state) is False

    def test_true_when_at_least_one_finding_qualifies(self):
        """If one finding qualifies among several, should still match."""
        state = create_initial_state("t")
        state["inspection_report"] = {
            "findings": [
                {"self_healable": False, "confidence": 0.1},
                {"self_healable": True, "confidence": 0.99},
            ]
        }
        assert known_error_pattern_matched(state) is True


class TestInspectionComplete:
    def test_true_when_no_pattern_matched(self):
        state = create_initial_state("t")
        state["inspection_report"] = {
            "findings": [
                {"self_healable": False, "confidence": 0.3}
            ]
        }
        assert inspection_complete(state) is True

    def test_false_when_pattern_matched(self):
        state = create_initial_state("t")
        state["inspection_report"] = {
            "findings": [
                {"self_healable": True, "confidence": 0.99}
            ]
        }
        assert inspection_complete(state) is False

    def test_inverse_of_known_error_pattern(self):
        state = create_initial_state("t")
        cases = [
            {"findings": []},
            {"findings": [{"self_healable": False, "confidence": 0.5}]},
            {"findings": [{"self_healable": True, "confidence": 0.99}]},
        ]
        for report in cases:
            state["inspection_report"] = report
            assert inspection_complete(state) != known_error_pattern_matched(state)


# ---------------------------------------------------------------------------
# Analysis guards
# ---------------------------------------------------------------------------

class TestAdjustmentsIdentified:
    def test_true_when_adjustments_present(self):
        state = create_initial_state("t")
        state["proposed_adjustments"] = [{"entry_id": "je-1"}]
        assert adjustments_identified(state) is True

    def test_false_when_no_adjustments(self):
        state = create_initial_state("t")
        state["proposed_adjustments"] = []
        assert adjustments_identified(state) is False

    def test_true_with_multiple_adjustments(self):
        state = create_initial_state("t")
        state["proposed_adjustments"] = [{"entry_id": "je-1"}, {"entry_id": "je-2"}]
        assert adjustments_identified(state) is True


class TestCleanAnalysis:
    def test_true_when_no_adjustments(self):
        state = create_initial_state("t")
        state["proposed_adjustments"] = []
        assert clean_analysis(state) is True

    def test_false_when_adjustments_present(self):
        state = create_initial_state("t")
        state["proposed_adjustments"] = [{"entry_id": "je-1"}]
        assert clean_analysis(state) is False

    def test_inverse_of_adjustments_identified(self):
        state = create_initial_state("t")
        for adj in [[], [{"x": 1}], [{"x": 1}, {"y": 2}]]:
            state["proposed_adjustments"] = adj
            assert clean_analysis(state) != adjustments_identified(state)


# ---------------------------------------------------------------------------
# Sign-off guards
# ---------------------------------------------------------------------------

class TestHumanApproves:
    def test_true_with_approve_and_sufficient_authority(self):
        state = create_initial_state("t")
        state["sign_off_decision"] = SignOffDecision.APPROVE
        state["sign_off_authority"] = AuthorityLevel.L3_MANAGER
        state["current_proposal"] = {
            "required_approval": {"authority_level": AuthorityLevel.L2_SENIOR}
        }
        assert human_approves(state) is True

    def test_true_with_matching_authority(self):
        state = create_initial_state("t")
        state["sign_off_decision"] = SignOffDecision.APPROVE
        state["sign_off_authority"] = AuthorityLevel.L2_SENIOR
        state["current_proposal"] = {
            "required_approval": {"authority_level": AuthorityLevel.L2_SENIOR}
        }
        assert human_approves(state) is True

    def test_false_with_insufficient_authority(self):
        state = create_initial_state("t")
        state["sign_off_decision"] = SignOffDecision.APPROVE
        state["sign_off_authority"] = AuthorityLevel.L1_STAFF
        state["current_proposal"] = {
            "required_approval": {"authority_level": AuthorityLevel.L3_MANAGER}
        }
        assert human_approves(state) is False

    def test_false_when_decision_is_reject(self):
        state = create_initial_state("t")
        state["sign_off_decision"] = SignOffDecision.REJECT
        state["sign_off_authority"] = AuthorityLevel.L4_CONTROLLER
        state["current_proposal"] = {
            "required_approval": {"authority_level": AuthorityLevel.L1_STAFF}
        }
        assert human_approves(state) is False

    def test_false_when_decision_is_escalate(self):
        state = create_initial_state("t")
        state["sign_off_decision"] = SignOffDecision.ESCALATE
        state["sign_off_authority"] = AuthorityLevel.L4_CONTROLLER
        assert human_approves(state) is False

    def test_true_with_controller_level(self):
        """Controller authority should approve any required level."""
        state = create_initial_state("t")
        state["sign_off_decision"] = SignOffDecision.APPROVE
        state["sign_off_authority"] = AuthorityLevel.L4_CONTROLLER
        state["current_proposal"] = {
            "required_approval": {"authority_level": AuthorityLevel.L4_CONTROLLER}
        }
        assert human_approves(state) is True

    def test_defaults_when_no_proposal(self):
        """When current_proposal is absent, defaults should allow approval at L1."""
        state = create_initial_state("t")
        state["sign_off_decision"] = SignOffDecision.APPROVE
        state["sign_off_authority"] = AuthorityLevel.L1_STAFF
        assert human_approves(state) is True


class TestHumanRejects:
    def test_true_when_reject(self):
        state = create_initial_state("t")
        state["sign_off_decision"] = SignOffDecision.REJECT
        assert human_rejects(state) is True

    def test_false_when_approve(self):
        state = create_initial_state("t")
        state["sign_off_decision"] = SignOffDecision.APPROVE
        assert human_rejects(state) is False

    def test_false_when_escalate(self):
        state = create_initial_state("t")
        state["sign_off_decision"] = SignOffDecision.ESCALATE
        assert human_rejects(state) is False


class TestHumanEscalates:
    def test_true_when_escalate(self):
        state = create_initial_state("t")
        state["sign_off_decision"] = SignOffDecision.ESCALATE
        assert human_escalates(state) is True

    def test_false_when_approve(self):
        state = create_initial_state("t")
        state["sign_off_decision"] = SignOffDecision.APPROVE
        assert human_escalates(state) is False

    def test_false_when_reject(self):
        state = create_initial_state("t")
        state["sign_off_decision"] = SignOffDecision.REJECT
        assert human_escalates(state) is False


class TestSignOffMutualExclusivity:
    """The three sign-off decisions should be mutually exclusive."""

    @pytest.mark.parametrize("decision", list(SignOffDecision))
    def test_exactly_one_guard_true_per_decision(self, decision):
        state = create_initial_state("t")
        state["sign_off_decision"] = decision
        state["sign_off_authority"] = AuthorityLevel.L4_CONTROLLER
        state["current_proposal"] = {
            "required_approval": {"authority_level": AuthorityLevel.L1_STAFF}
        }
        results = [
            human_approves(state),
            human_rejects(state),
            human_escalates(state),
        ]
        assert sum(results) == 1, (
            f"Expected exactly one True for decision={decision}, got {results}"
        )


# ---------------------------------------------------------------------------
# Commit guards
# ---------------------------------------------------------------------------

class TestMutationSucceeds:
    def test_true_when_ack(self):
        state = create_initial_state("t")
        state["commit_result"] = CommitResult.ACK
        assert mutation_succeeds(state) is True

    def test_false_when_nack(self):
        state = create_initial_state("t")
        state["commit_result"] = CommitResult.NACK
        assert mutation_succeeds(state) is False

    def test_false_when_not_set(self):
        state = create_initial_state("t")
        assert mutation_succeeds(state) is False


class TestMutationFails:
    def test_true_when_nack(self):
        state = create_initial_state("t")
        state["commit_result"] = CommitResult.NACK
        assert mutation_fails(state) is True

    def test_false_when_ack(self):
        state = create_initial_state("t")
        state["commit_result"] = CommitResult.ACK
        assert mutation_fails(state) is False

    def test_false_when_not_set(self):
        state = create_initial_state("t")
        assert mutation_fails(state) is False

    def test_inverse_when_set(self):
        state = create_initial_state("t")
        for result in [CommitResult.ACK, CommitResult.NACK]:
            state["commit_result"] = result
            assert mutation_succeeds(state) != mutation_fails(state)


# ---------------------------------------------------------------------------
# Self-heal guards
# ---------------------------------------------------------------------------

class TestCorrectionGenerated:
    def test_true_when_correction_present(self):
        state = create_initial_state("t")
        state["self_heal_correction"] = {"pattern_id": "AW-001", "amount": "500"}
        assert correction_generated(state) is True

    def test_false_when_correction_absent(self):
        state = create_initial_state("t")
        assert correction_generated(state) is False

    def test_false_when_correction_is_none(self):
        state = create_initial_state("t")
        state["self_heal_correction"] = None
        assert correction_generated(state) is False

    def test_true_with_empty_dict(self):
        """An empty dict is not None, so correction_generated returns True."""
        state = create_initial_state("t")
        state["self_heal_correction"] = {}
        assert correction_generated(state) is True
