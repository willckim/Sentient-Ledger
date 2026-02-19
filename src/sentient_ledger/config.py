"""Thresholds and constants for the Sentient Ledger."""

from decimal import Decimal

from sentient_ledger.models.enums import AuthorityLevel

# Ingest thresholds
MALFORMED_ROW_THRESHOLD_PCT = 1.0  # max % of malformed rows before quarantine

# Compliance thresholds
TRIAL_BALANCE_TOLERANCE = Decimal("0.01")
DEPRECIATION_VARIANCE_ABS = Decimal("500.00")
DEPRECIATION_VARIANCE_PCT = Decimal("0.02")
IMPAIRMENT_THRESHOLD_PCT = Decimal("0.10")
USEFUL_LIFE_MISMATCH_MONTHS = 6

# Self-heal confidence threshold
SELF_HEAL_CONFIDENCE_THRESHOLD = 0.95

# Authority level thresholds (max single adjustment)
AUTHORITY_THRESHOLDS = {
    AuthorityLevel.L1_STAFF: Decimal("5000.00"),
    AuthorityLevel.L2_SENIOR: Decimal("50000.00"),
    AuthorityLevel.L3_MANAGER: Decimal("500000.00"),
    AuthorityLevel.L4_CONTROLLER: None,  # unlimited
}

# Eval gate thresholds
EVAL_GATE_RECALL = 0.98
EVAL_GATE_PRECISION = 0.95
EVAL_GATE_CRITICAL_RECALL = 1.00
EVAL_GATE_CORRECTION_ACCURACY = 0.97
EVAL_GATE_MAX_ERROR = Decimal("1.00")

# SLA hours per authority level (time for human review)
AUTHORITY_SLA_HOURS: dict[AuthorityLevel, float] = {
    AuthorityLevel.L1_STAFF: 4.0,
    AuthorityLevel.L2_SENIOR: 8.0,
    AuthorityLevel.L3_MANAGER: 24.0,
    AuthorityLevel.L4_CONTROLLER: 48.0,
}

# Escalation path: who to escalate to when SLA expires
AUTHORITY_ESCALATION: dict[AuthorityLevel, AuthorityLevel] = {
    AuthorityLevel.L1_STAFF: AuthorityLevel.L2_SENIOR,
    AuthorityLevel.L2_SENIOR: AuthorityLevel.L3_MANAGER,
    AuthorityLevel.L3_MANAGER: AuthorityLevel.L4_CONTROLLER,
    AuthorityLevel.L4_CONTROLLER: AuthorityLevel.L4_CONTROLLER,
}

# Schema version
SCHEMA_VERSION = "0.1.0"
