"""D365 ingestion pipeline — CSV parsing, column mapping, validation."""

from sentient_ledger.ingest.adapter import adapt_state_for_detector
from sentient_ledger.ingest.pipeline import (
    ingest_d365_export,
    ingest_depreciation_schedule,
    ingest_fixed_assets,
    ingest_trial_balance,
)

__all__ = [
    "ingest_d365_export",
    "ingest_trial_balance",
    "ingest_fixed_assets",
    "ingest_depreciation_schedule",
    "adapt_state_for_detector",
]
