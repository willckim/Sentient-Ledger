"""Tests for ingest pipeline orchestrator."""

import pytest

from sentient_ledger.ingest.pipeline import (
    IngestionResult,
    ingest_d365_export,
    ingest_depreciation_schedule,
    ingest_fixed_assets,
    ingest_trial_balance,
)


# -- Inline CSV fixtures --

CLEAN_TB_CSV = """\
MainAccount,AccountName,BusinessUnit,Department,CostCenter,OpeningBalance,Debits,Credits,ClosingBalance,TransactionCurrency,ReportingCurrency,ExchangeRate,CalendarMonth
110100,Cash - Operating,BU-001,FIN,CC-100,100000.00,50000.00,30000.00,120000.00,USD,USD,1.00,2026-01
200100,Accounts Payable,BU-001,FIN,CC-100,50000.00,10000.00,25000.00,65000.00,USD,USD,1.00,2026-01
"""

CLEAN_FA_CSV = """\
AssetId,AssetGroup,Description,AcquisitionDate,AcquisitionCost,DepreciationMethod,ServiceLife,ServiceLifeUnit,SalvageValue,Convention,AccumulatedDepreciation,NetBookValue,Status
FA-001,MACHINERY,CNC Machine,2024-01-15,500000.00,StraightLine,10,Years,50000.00,HalfMonth,90000.00,410000.00,Open
FA-002,FURNITURE,Office Desk,2024-06-01,5000.00,StraightLine,5,Years,500.00,FullMonth,750.00,4250.00,Open
"""

ERROR_TB_CSV = """\
MainAccount,AccountName,BusinessUnit,Department,CostCenter,OpeningBalance,Debits,Credits,ClosingBalance,TransactionCurrency,ReportingCurrency,ExchangeRate,CalendarMonth
110100,Cash,BU-001,FIN,CC-100,100000.00,50000.00,30000.00,120000.00,USD,USD,1.00,2026-01
,Missing Account,BU-001,FIN,CC-100,5000.00,1000.00,500.00,5500.00,USD,USD,1.00,2026-01
200100,AP,BU-001,FIN,CC-100,50000.00,-500.00,25000.00,24500.00,USD,USD,1.00,2026-01
300100,Equity,BU-001,FIN,CC-100,80000.00,5000.00,3000.00,82000.00,XYZ,USD,1.00,2026-01
400100,Revenue,BU-001,FIN,CC-100,0.00,0.00,75000.00,75000.00,USD,USD,1.00,2026-01
"""


class TestIngestTrialBalance:
    def test_clean_csv(self):
        result = ingest_trial_balance(csv_content=CLEAN_TB_CSV, ingestion_id="T001")
        assert result.total_rows == 2
        assert len(result.trial_balance_records) == 2
        assert result.malformed_rows == 0
        assert result.malformed_pct == 0.0

    def test_error_csv_identifies_malformed(self):
        result = ingest_trial_balance(csv_content=ERROR_TB_CSV)
        assert result.total_rows == 5
        assert result.malformed_rows == 3  # empty account, negative debits, XYZ currency
        assert len(result.trial_balance_records) == 2  # 2 clean rows

    def test_malformed_pct_computation(self):
        result = ingest_trial_balance(csv_content=ERROR_TB_CSV)
        assert result.malformed_pct == pytest.approx(60.0)

    def test_no_input_raises(self):
        with pytest.raises(ValueError, match="file_path or csv_content"):
            ingest_trial_balance()


class TestIngestFixedAssets:
    def test_clean_csv(self):
        result = ingest_fixed_assets(csv_content=CLEAN_FA_CSV, ingestion_id="F001")
        assert result.total_rows == 2
        assert len(result.asset_register) == 2
        assert result.malformed_rows == 0

    def test_enum_translations_in_output(self):
        result = ingest_fixed_assets(csv_content=CLEAN_FA_CSV)
        rec = result.asset_register[0]
        assert rec["acquisition"]["method"] == "STRAIGHT_LINE"
        assert rec["acquisition"]["convention"] == "HALF_MONTH"
        assert rec["current_state"]["status"] == "ACTIVE"


class TestIngestD365Export:
    def test_combined_export(self):
        result = ingest_d365_export(tb_content=CLEAN_TB_CSV, fa_content=CLEAN_FA_CSV)
        assert len(result.trial_balance_records) == 2
        assert len(result.asset_register) == 2
        assert result.total_rows == 4
        assert result.malformed_rows == 0

    def test_to_state_dict_keys(self):
        result = ingest_d365_export(tb_content=CLEAN_TB_CSV, fa_content=CLEAN_FA_CSV)
        state = result.to_state_dict()
        expected_keys = {
            "trial_balance_records",
            "asset_register",
            "depreciation_schedule",
            "total_rows",
            "malformed_rows",
            "malformed_pct",
        }
        assert set(state.keys()) == expected_keys


CLEAN_DS_CSV = """\
AssetId,Period,DepreciationAmount,AccumulatedDepreciation,NetBookValue
FA-001,2024-01,1875.00,1875.00,498125.00
FA-001,2024-02,3750.00,5625.00,494375.00
FA-002,2024-06,75.00,75.00,4925.00
"""

ERROR_DS_CSV = """\
AssetId,Period,DepreciationAmount,AccumulatedDepreciation,NetBookValue
FA-001,2024-01,1875.00,1875.00,498125.00
FA-001,BAD-PERIOD,3750.00,5625.00,494375.00
FA-002,2024-06,-100.00,75.00,4925.00
"""


class TestIngestDepreciationSchedule:
    def test_clean_csv(self):
        result = ingest_depreciation_schedule(csv_content=CLEAN_DS_CSV, ingestion_id="DS001")
        assert result.total_rows == 3
        assert len(result.depreciation_schedule) == 3
        assert result.malformed_rows == 0

    def test_error_csv_identifies_malformed(self):
        result = ingest_depreciation_schedule(csv_content=ERROR_DS_CSV)
        assert result.total_rows == 3
        assert result.malformed_rows >= 2  # bad period + negative amount
        assert len(result.depreciation_schedule) == 1  # only first row clean

    def test_no_input_raises(self):
        with pytest.raises(ValueError, match="file_path or csv_content"):
            ingest_depreciation_schedule()

    def test_combined_export_with_ds(self):
        result = ingest_d365_export(
            tb_content=CLEAN_TB_CSV, fa_content=CLEAN_FA_CSV, ds_content=CLEAN_DS_CSV,
        )
        assert len(result.depreciation_schedule) == 3
        assert result.total_rows == 7  # 2 TB + 2 FA + 3 DS
