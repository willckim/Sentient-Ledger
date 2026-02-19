"""Column mappings, enum translations, and validation rules for D365 exports."""

# ---------------------------------------------------------------------------
# Trial Balance column map: D365 header → canonical dotted path
# ---------------------------------------------------------------------------
TB_COLUMN_MAP: dict[str, str] = {
    "MainAccount": "account.code",
    "AccountName": "account.name",
    "BusinessUnit": "dimensions.business_unit",
    "Department": "dimensions.department",
    "CostCenter": "dimensions.cost_center",
    "OpeningBalance": "balances.opening",
    "Debits": "balances.debits",
    "Credits": "balances.credits",
    "ClosingBalance": "balances.closing",
    "TransactionCurrency": "currency.transaction",
    "ReportingCurrency": "currency.reporting",
    "ExchangeRate": "currency.exchange_rate",
    "CalendarMonth": "period.calendar_month",
}

TB_REQUIRED_COLUMNS: set[str] = {
    "MainAccount",
    "AccountName",
    "BusinessUnit",
    "OpeningBalance",
    "Debits",
    "Credits",
    "ClosingBalance",
    "CalendarMonth",
}

TB_DECIMAL_FIELDS: set[str] = {
    "OpeningBalance",
    "Debits",
    "Credits",
    "ClosingBalance",
    "ExchangeRate",
}

# ---------------------------------------------------------------------------
# Fixed Assets column map: D365 header → canonical dotted path
# ---------------------------------------------------------------------------
FA_COLUMN_MAP: dict[str, str] = {
    "AssetId": "identity.asset_id",
    "AssetGroup": "identity.group",
    "Description": "identity.description",
    "AcquisitionDate": "acquisition.date",
    "AcquisitionCost": "acquisition.cost",
    "DepreciationMethod": "acquisition.method",
    "ServiceLife": "acquisition.useful_life_months",
    "ServiceLifeUnit": "_service_life_unit",
    "SalvageValue": "acquisition.salvage_value",
    "Convention": "acquisition.convention",
    "AccumulatedDepreciation": "current_state.accumulated_depreciation",
    "NetBookValue": "current_state.net_book_value",
    "Status": "current_state.status",
}

FA_REQUIRED_COLUMNS: set[str] = {
    "AssetId",
    "AssetGroup",
    "Description",
    "AcquisitionDate",
    "AcquisitionCost",
    "DepreciationMethod",
    "ServiceLife",
    "SalvageValue",
    "AccumulatedDepreciation",
    "NetBookValue",
    "Status",
}

FA_DECIMAL_FIELDS: set[str] = {
    "AcquisitionCost",
    "SalvageValue",
    "AccumulatedDepreciation",
    "NetBookValue",
}

FA_INTEGER_FIELDS: set[str] = {
    "ServiceLife",
}

# ---------------------------------------------------------------------------
# Enum translation maps: D365 value → canonical enum value
# ---------------------------------------------------------------------------
DEPRECIATION_METHOD_MAP: dict[str, str] = {
    "StraightLine": "STRAIGHT_LINE",
    "ReducingBalance": "DOUBLE_DECLINING",
    "SumOfYears": "SUM_OF_YEARS",
    "UnitsOfProduction": "UNITS_OF_PRODUCTION",
    "MACRS": "MACRS",
}

DEPRECIATION_CONVENTION_MAP: dict[str, str] = {
    "FullMonth": "FULL_MONTH",
    "HalfMonth": "HALF_MONTH",
    "MidMonth": "MID_MONTH",
    "HalfYear": "HALF_YEAR",
    "MidQuarter": "MID_QUARTER",
}

ASSET_STATUS_MAP: dict[str, str] = {
    "Open": "ACTIVE",
    "Closed": "FULLY_DEPRECIATED",
    "Disposed": "DISPOSED",
    "Suspended": "SUSPENDED",
}

# ---------------------------------------------------------------------------
# Validation rules: (rule_name, severity)
# ---------------------------------------------------------------------------
TB_VALIDATIONS: list[tuple[str, str]] = [
    ("debits_non_negative", "ERROR"),
    ("credits_non_negative", "ERROR"),
    ("account_code_min_length", "WARNING"),
    ("currency_supported", "ERROR"),
]

FA_VALIDATIONS: list[tuple[str, str]] = [
    ("cost_positive", "ERROR"),
    ("salvage_non_negative", "ERROR"),
    ("salvage_less_than_cost", "ERROR"),
    ("useful_life_positive", "ERROR"),
    ("nbv_non_negative", "WARNING"),
]

# ---------------------------------------------------------------------------
# Depreciation Schedule column map: D365 header → flat key
# ---------------------------------------------------------------------------
DS_COLUMN_MAP: dict[str, str] = {
    "AssetId": "asset_id",
    "Period": "period",
    "DepreciationAmount": "amount",
    "AccumulatedDepreciation": "accumulated",
    "NetBookValue": "net_book_value",
}

DS_REQUIRED_COLUMNS: set[str] = {
    "AssetId",
    "Period",
    "DepreciationAmount",
    "AccumulatedDepreciation",
    "NetBookValue",
}

DS_DECIMAL_FIELDS: set[str] = {
    "DepreciationAmount",
    "AccumulatedDepreciation",
    "NetBookValue",
}

DS_VALIDATIONS: list[tuple[str, str]] = [
    ("amount_non_negative", "ERROR"),
    ("accumulated_non_negative", "ERROR"),
    ("nbv_non_negative", "WARNING"),
    ("period_format_valid", "ERROR"),
]

# ---------------------------------------------------------------------------
# Supported currencies
# ---------------------------------------------------------------------------
SUPPORTED_CURRENCIES: set[str] = {"USD", "EUR", "GBP", "CAD", "AUD", "JPY", "CHF"}
