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

# ---------------------------------------------------------------------------
# MCP Server configuration
# ---------------------------------------------------------------------------

# Default timeout for all MCP server tool calls (seconds)
MCP_SERVER_TIMEOUT_SEC: float = 30.0
MCP_MAX_RETRIES: int = 3

# Business Central company identifiers
BC_COMPANIES: dict[str, str] = {
    "ortho": "Ortho Molecular Products",
    "utzy": "Utzy Naturals",
}

# Default BC environment
BC_ENVIRONMENT: str = "production"

# SAP Concur pay group for Ortho expense reports
CONCUR_PAY_GROUP: str = "OMPI-EXP"

# US states that use combined filing (Avalara)
AVALARA_COMBINED_FILING_STATES: frozenset[str] = frozenset(
    {"HI", "IA", "MO", "NM", "OH", "SC", "TN", "UT", "WA"}
)

# Tango Card approved reward brands
TANGO_APPROVED_BRANDS: frozenset[str] = frozenset(
    {
        "Amazon",
        "Visa",
        "Mastercard",
        "Target",
        "Walmart",
        "Starbucks",
        "Apple",
        "Google Play",
        "PayPal",
        "Venmo",
    }
)

# Network drive root paths (Windows → Mac fallback)
FILE_SYSTEM_DRIVE_WINDOWS: str = r"N:\\"
FILE_SYSTEM_DRIVE_MAC: str = "/Volumes/Network"
