"""Canonical trial balance models."""

from decimal import Decimal

from pydantic import BaseModel

from sentient_ledger.models.enums import AccountCategory


class AccountInfo(BaseModel):
    code: str
    name: str
    category: AccountCategory
    sub_category: str = ""
    is_control_account: bool = False


class Dimensions(BaseModel):
    business_unit: str
    department: str | None = None
    cost_center: str | None = None
    composite_key: str = ""


class Balances(BaseModel):
    opening: Decimal
    debits: Decimal
    credits: Decimal
    closing: Decimal
    movement: Decimal = Decimal("0")


class CurrencyInfo(BaseModel):
    transaction: str = "USD"
    reporting: str = "USD"
    exchange_rate: Decimal | None = None


class PeriodInfo(BaseModel):
    fiscal_year: int
    fiscal_period: int
    calendar_month: str


class IntegrityInfo(BaseModel):
    source_row_hash: str = ""
    balance_verified: bool = False


class CanonicalTrialBalance(BaseModel):
    record_id: str
    source: str = "DYNAMICS_365"
    ingestion_id: str = ""
    ingested_at: str = ""
    account: AccountInfo
    dimensions: Dimensions
    balances: Balances
    currency: CurrencyInfo = CurrencyInfo()
    period: PeriodInfo
    integrity: IntegrityInfo = IntegrityInfo()
