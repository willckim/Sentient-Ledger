"""BMO CSV column mappings, vendor patterns, and validation rules."""

from sentient_ledger.models.enums import VendorCategory

# ---------------------------------------------------------------------------
# Column name mappings: BMO CSV header → canonical field name
# ---------------------------------------------------------------------------

BMO_COLUMN_MAP: dict[str, str] = {
    "Posted": "posted_date",
    "Value Date": "value_date",
    "Description": "description",
    "Debit": "debit",
    "Credit": "credit",
    "Balance": "balance",
    "Bank Rec #": "bank_rec_number",
    "CC Merchant Rec Date": "cc_merchant_rec_date",
}

BMO_REQUIRED_COLUMNS: set[str] = {"Posted", "Value Date", "Description", "Balance"}

BMO_DECIMAL_FIELDS: set[str] = {"Debit", "Credit", "Balance"}

# ---------------------------------------------------------------------------
# Vendor classification: ordered list of (substring, VendorCategory).
# More specific patterns MUST come before generic ones.
# ---------------------------------------------------------------------------

VENDOR_PATTERNS: list[tuple[str, VendorCategory]] = [
    # CC merchant settlements / fees — ELAVON specific sub-types first
    ("ELAVON CMS", VendorCategory.CC_MERCHANT_FEE),
    ("ELAVON GES", VendorCategory.CC_MERCHANT_FEE),
    ("ELAVON", VendorCategory.CC_MERCHANT_SETTLEMENT),
    # AMEX settlement
    ("AMEX", VendorCategory.AMEX_SETTLEMENT),
    # Service charges — rebate MUST come before plain fee
    ("FULL PLAN FEE REBATE", VendorCategory.BANK_FEE_REBATE),
    ("PLAN FEE", VendorCategory.BANK_FEE),
    # Other bank fees / rebates
    ("SERVICE CHARGE", VendorCategory.BANK_FEE),
    ("BANK FEE", VendorCategory.BANK_FEE),
    # Payment processing / ACH
    ("PAYROLL", VendorCategory.PAYMENT_PROCESSING),
    ("ACH", VendorCategory.PAYMENT_PROCESSING),
    ("WIRE", VendorCategory.PAYMENT_PROCESSING),
    # Retirement plan
    ("401K", VendorCategory.RETIREMENT_PLAN),
    ("PENSION", VendorCategory.RETIREMENT_PLAN),
    ("RETIREMENT", VendorCategory.RETIREMENT_PLAN),
]

# Categories that require CC Merchant Rec Date to be populated
CC_MERCHANT_REC_CATEGORIES: set[str] = {
    VendorCategory.CC_MERCHANT_SETTLEMENT.value,
    VendorCategory.AMEX_SETTLEMENT.value,
}

# Description substrings used to match service charge pairs
SERVICE_CHARGE_FEE_PATTERN: str = "PLAN FEE"
SERVICE_CHARGE_REBATE_PATTERN: str = "FULL PLAN FEE REBATE"

# ---------------------------------------------------------------------------
# Validation rules
# ---------------------------------------------------------------------------

BMO_VALIDATIONS: list[dict] = [
    {
        "rule": "DEBIT_CREDIT_EXCLUSIVE",
        "severity": "ERROR",
        "description": "A row must not have both Debit and Credit populated.",
    },
    {
        "rule": "RUNNING_BALANCE",
        "severity": "ERROR",
        "description": "Sequential balance must equal previous balance ± transaction amount.",
    },
    {
        "rule": "NO_DUPLICATES",
        "severity": "ERROR",
        "description": "No two rows may share the same (posted_date, description, amount, type).",
    },
    {
        "rule": "SERVICE_CHARGE_PAIRS",
        "severity": "WARNING",
        "description": "Each PLAN FEE should be offset by a matching FULL PLAN FEE REBATE.",
    },
    {
        "rule": "CC_MERCHANT_REC_DATE",
        "severity": "WARNING",
        "description": "ELAVON/AMEX rows should have CC Merchant Rec Date populated.",
    },
]
