"""Unit tests for package API surface exports."""


class TestTopLevelImports:
    def test_top_level_imports(self):
        from sentient_ledger import (
            SCHEMA_VERSION,
            build_reconciliation_graph,
            create_initial_state,
        )

        assert callable(build_reconciliation_graph)
        assert callable(create_initial_state)
        assert isinstance(SCHEMA_VERSION, str)


class TestIngestPackageImports:
    def test_ingest_package_imports(self):
        from sentient_ledger.ingest import (
            adapt_state_for_detector,
            ingest_d365_export,
            ingest_depreciation_schedule,
            ingest_fixed_assets,
            ingest_trial_balance,
        )

        assert callable(ingest_d365_export)
        assert callable(ingest_trial_balance)
        assert callable(ingest_fixed_assets)
        assert callable(ingest_depreciation_schedule)
        assert callable(adapt_state_for_detector)


class TestEnginePackageImports:
    def test_engine_package_imports(self):
        from sentient_ledger.engine import (
            calculate_monthly_depreciation,
            detect_errors,
            evaluate_detection,
        )

        assert callable(detect_errors)
        assert callable(calculate_monthly_depreciation)
        assert callable(evaluate_detection)
