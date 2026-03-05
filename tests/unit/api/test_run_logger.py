"""Unit tests for api/run_logger.py."""

import json

import pytest

from sentient_ledger.api.run_logger import RunLogger, RunRecord
from sentient_ledger.models.enums import BankRecWorkflow


def _record(**overrides) -> RunRecord:
    defaults = dict(
        run_id="test-run",
        workflow=BankRecWorkflow.POST_NEW_LINES,
        timestamp="2026-03-04T00:00:00+00:00",
        user_id="alice",
        input_file_name="bmo.csv",
        input_file_hash="abc123",
        output_file_hash=None,
        status="ok",
        error_count=0,
        warning_count=0,
        new_rows=5,
        total_rows=7,
        audit_record_hashes=["h1", "h2"],
        duration_ms=120,
    )
    defaults.update(overrides)
    return RunRecord(**defaults)


class TestRunRecord:
    def test_compute_hash_non_empty(self):
        r = _record()
        assert r.compute_hash() != ""

    def test_compute_hash_deterministic(self):
        r1 = _record()
        r2 = _record()
        assert r1.compute_hash() == r2.compute_hash()

    def test_different_content_different_hash(self):
        r1 = _record(new_rows=1)
        r2 = _record(new_rows=99)
        assert r1.compute_hash() != r2.compute_hash()

    def test_run_hash_field_excluded_from_compute(self):
        """run_hash must not feed back into compute_hash (no circularity)."""
        r = _record()
        h1 = r.compute_hash()
        r2 = r.model_copy(update={"run_hash": "some-previous-value"})
        assert r2.compute_hash() == h1

    def test_serializes_to_json(self):
        r = _record()
        raw = r.model_dump_json()
        assert json.loads(raw)["user_id"] == "alice"


class TestRunLogger:
    def test_creates_log_file_on_first_write(self, tmp_path):
        logger = RunLogger(tmp_path / "runs.jsonl")
        logger.log(_record())
        assert (tmp_path / "runs.jsonl").exists()

    def test_log_path_parent_auto_created(self, tmp_path):
        deep = tmp_path / "logs" / "sub" / "runs.jsonl"
        RunLogger(deep).log(_record())
        assert deep.exists()

    def test_logged_record_has_non_empty_run_hash(self, tmp_path):
        logged = RunLogger(tmp_path / "runs.jsonl").log(_record())
        assert logged.run_hash != ""

    def test_first_record_previous_hash_empty(self, tmp_path):
        logged = RunLogger(tmp_path / "runs.jsonl").log(_record())
        assert logged.previous_run_hash == ""

    def test_second_record_chains_to_first(self, tmp_path):
        logger = RunLogger(tmp_path / "runs.jsonl")
        first = logger.log(_record(run_id="r1"))
        second = logger.log(_record(run_id="r2"))
        assert second.previous_run_hash == first.run_hash

    def test_chain_is_transitive(self, tmp_path):
        logger = RunLogger(tmp_path / "runs.jsonl")
        r1 = logger.log(_record(run_id="r1"))
        r2 = logger.log(_record(run_id="r2"))
        r3 = logger.log(_record(run_id="r3"))
        assert r2.previous_run_hash == r1.run_hash
        assert r3.previous_run_hash == r2.run_hash

    def test_read_all_empty_returns_empty_list(self, tmp_path):
        logger = RunLogger(tmp_path / "runs.jsonl")
        assert logger.read_all() == []

    def test_read_all_nonexistent_file_returns_empty(self, tmp_path):
        logger = RunLogger(tmp_path / "nonexistent.jsonl")
        assert logger.read_all() == []

    def test_read_all_returns_all_records_in_order(self, tmp_path):
        logger = RunLogger(tmp_path / "runs.jsonl")
        logger.log(_record(run_id="r1"))
        logger.log(_record(run_id="r2"))
        logger.log(_record(run_id="r3"))
        records = logger.read_all()
        assert len(records) == 3
        assert records[0].run_id == "r1"
        assert records[2].run_id == "r3"

    def test_run_hash_stored_in_file(self, tmp_path):
        log_path = tmp_path / "runs.jsonl"
        logged = RunLogger(log_path).log(_record())
        line = json.loads(log_path.read_text().strip())
        assert line["run_hash"] == logged.run_hash

    def test_different_runs_different_hashes(self, tmp_path):
        logger = RunLogger(tmp_path / "runs.jsonl")
        r1 = logger.log(_record(run_id="r1", new_rows=1))
        r2 = logger.log(_record(run_id="r2", new_rows=9))
        assert r1.run_hash != r2.run_hash

    def test_workflow_serialized_as_string(self, tmp_path):
        log_path = tmp_path / "runs.jsonl"
        RunLogger(log_path).log(_record(workflow=BankRecWorkflow.RECONCILE_GL))
        line = json.loads(log_path.read_text().strip())
        assert line["workflow"] == "RECONCILE_GL"
