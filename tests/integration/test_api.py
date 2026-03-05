"""Integration tests for the Sentient Ledger REST API."""

from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

FIXTURES = Path(__file__).parent.parent / "fixtures" / "bmo"


def _bmo_clean() -> bytes:
    return (FIXTURES / "bmo_download_clean.csv").read_bytes()


def _bmo_full() -> bytes:
    return (FIXTURES / "bmo_download.csv").read_bytes()


def _bmo_file(content: bytes = None) -> dict:
    """Return a files dict for multipart upload."""
    return {"bmo_file": ("bmo.csv", content or _bmo_full(), "text/csv")}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def app_env(tmp_path, monkeypatch):
    """Isolate the run log to tmp_path for each test."""
    log_path = tmp_path / "runs.jsonl"
    monkeypatch.setenv("SENTIENT_LEDGER_RUNS_LOG", str(log_path))
    return log_path


@pytest.fixture()
def client(app_env):
    # Import after monkeypatching so Settings.from_env() picks up the temp path.
    from sentient_ledger.api.app import create_app

    return TestClient(create_app())


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------


class TestHealth:
    def test_returns_200(self, client):
        assert client.get("/health").status_code == 200

    def test_body_has_ok_status(self, client):
        assert client.get("/health").json()["status"] == "ok"

    def test_body_has_version(self, client):
        assert "version" in client.get("/health").json()


# ---------------------------------------------------------------------------
# POST /bank-rec/post-new-lines
# ---------------------------------------------------------------------------


class TestPostNewLines:
    def test_returns_200(self, client):
        resp = client.post(
            "/bank-rec/post-new-lines",
            files=_bmo_file(_bmo_clean()),
            data={"opening_balance": "100000"},
        )
        assert resp.status_code == 200

    def test_response_has_all_required_fields(self, client):
        resp = client.post(
            "/bank-rec/post-new-lines",
            files=_bmo_file(_bmo_clean()),
            data={"opening_balance": "100000"},
        )
        body = resp.json()
        for field in [
            "run_id", "workflow", "status", "timestamp", "user_id",
            "input_file_hash", "validation", "audit_chain", "run_hash",
        ]:
            assert field in body, f"Missing field: {field}"

    def test_workflow_value_correct(self, client):
        resp = client.post(
            "/bank-rec/post-new-lines",
            files=_bmo_file(_bmo_clean()),
            data={"opening_balance": "100000"},
        )
        assert resp.json()["workflow"] == "POST_NEW_LINES"

    def test_output_csv_returned_as_valid_base64(self, client):
        resp = client.post(
            "/bank-rec/post-new-lines",
            files=_bmo_file(_bmo_clean()),
            data={"opening_balance": "100000"},
        )
        b64 = resp.json().get("output_csv_b64")
        assert b64 is not None
        decoded = base64.b64decode(b64).decode()
        # post_new_lines CSV contains record_id column
        assert "record_id" in decoded

    def test_user_id_from_header(self, client):
        resp = client.post(
            "/bank-rec/post-new-lines",
            files=_bmo_file(_bmo_clean()),
            data={"opening_balance": "100000"},
            headers={"X-User-ID": "alice@ortho.com"},
        )
        assert resp.json()["user_id"] == "alice@ortho.com"

    def test_anonymous_when_no_x_user_id_header(self, client):
        resp = client.post(
            "/bank-rec/post-new-lines",
            files=_bmo_file(_bmo_clean()),
            data={"opening_balance": "100000"},
        )
        assert resp.json()["user_id"] == "anonymous"

    def test_validation_summary_in_response(self, client):
        resp = client.post(
            "/bank-rec/post-new-lines",
            files=_bmo_file(_bmo_clean()),
            data={"opening_balance": "100000"},
        )
        v = resp.json()["validation"]
        assert "error_count" in v
        assert "new_rows" in v
        assert "total_rows" in v

    def test_run_hash_non_empty(self, client):
        resp = client.post(
            "/bank-rec/post-new-lines",
            files=_bmo_file(_bmo_clean()),
            data={"opening_balance": "100000"},
        )
        assert resp.json()["run_hash"] != ""


# ---------------------------------------------------------------------------
# POST /bank-rec/reconcile-gl
# ---------------------------------------------------------------------------


class TestReconcileGL:
    def test_returns_200(self, client):
        resp = client.post("/bank-rec/reconcile-gl", files=_bmo_file())
        assert resp.status_code == 200

    def test_workflow_value_correct(self, client):
        assert client.post(
            "/bank-rec/reconcile-gl", files=_bmo_file()
        ).json()["workflow"] == "RECONCILE_GL"

    def test_output_csv_has_bc_bank_rec_columns(self, client):
        resp = client.post("/bank-rec/reconcile-gl", files=_bmo_file())
        b64 = resp.json().get("output_csv_b64")
        if b64:
            content = base64.b64decode(b64).decode()
            assert "Transaction Date" in content
            assert "Description" in content
            assert "Amount" in content

    def test_output_filename_is_set(self, client):
        resp = client.post("/bank-rec/reconcile-gl", files=_bmo_file())
        filename = resp.json().get("output_filename")
        if resp.json().get("output_csv_b64"):
            assert filename == "bank_rec_import.csv"


# ---------------------------------------------------------------------------
# POST /bank-rec/reconcile-amex
# ---------------------------------------------------------------------------


class TestReconcileAmex:
    def test_returns_200(self, client):
        resp = client.post(
            "/bank-rec/reconcile-amex",
            files=_bmo_file(),
            data={"cutoff_date": "2026-03-05"},
        )
        assert resp.status_code == 200

    def test_workflow_value_correct(self, client):
        resp = client.post(
            "/bank-rec/reconcile-amex",
            files=_bmo_file(),
        )
        assert resp.json()["workflow"] == "RECONCILE_AMEX"

    def test_new_rows_is_amex_count(self, client):
        resp = client.post(
            "/bank-rec/reconcile-amex",
            files=_bmo_file(),
            data={"cutoff_date": "2026-03-05"},
        )
        # bmo_download.csv has 2 AMEX rows
        assert resp.json()["validation"]["new_rows"] == 2

    def test_invalid_cutoff_date_returns_422(self, client):
        resp = client.post(
            "/bank-rec/reconcile-amex",
            files=_bmo_file(),
            data={"cutoff_date": "not-a-date"},
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# POST /bank-rec/cash-receipt-journal
# ---------------------------------------------------------------------------


class TestCashReceiptJournal:
    def test_returns_200(self, client):
        resp = client.post(
            "/bank-rec/cash-receipt-journal",
            files=_bmo_file(),
            data={"account_no": "11200", "cutoff_date": "2026-03-05"},
        )
        assert resp.status_code == 200

    def test_workflow_value_correct(self, client):
        resp = client.post(
            "/bank-rec/cash-receipt-journal",
            files=_bmo_file(),
            data={"account_no": "11200"},
        )
        assert resp.json()["workflow"] == "CASH_RECEIPT_JOURNAL"

    def test_output_csv_has_bc_cj_columns(self, client):
        resp = client.post(
            "/bank-rec/cash-receipt-journal",
            files=_bmo_file(),
            data={"account_no": "11200", "cutoff_date": "2026-03-05"},
        )
        b64 = resp.json().get("output_csv_b64")
        if b64:
            content = base64.b64decode(b64).decode()
            assert "Posting Date" in content
            assert "Document No." in content
            assert "Account No." in content

    def test_output_filename_is_ccamex(self, client):
        resp = client.post(
            "/bank-rec/cash-receipt-journal",
            files=_bmo_file(),
            data={"account_no": "11200", "cutoff_date": "2026-03-05"},
        )
        if resp.json().get("output_csv_b64"):
            assert resp.json()["output_filename"] == "ccamex.csv"

    def test_missing_account_no_returns_422(self, client):
        resp = client.post(
            "/bank-rec/cash-receipt-journal",
            files=_bmo_file(),
            # no account_no form field
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Run log / audit chain
# ---------------------------------------------------------------------------


class TestRunLog:
    def test_run_logged_to_jsonl(self, client, app_env):
        client.post("/bank-rec/reconcile-gl", files=_bmo_file())
        assert app_env.exists()
        records = [json.loads(l) for l in app_env.read_text().splitlines() if l.strip()]
        assert len(records) == 1
        assert records[0]["workflow"] == "RECONCILE_GL"

    def test_user_id_persisted_in_run_log(self, client, app_env):
        client.post(
            "/bank-rec/reconcile-gl",
            files=_bmo_file(),
            headers={"X-User-ID": "bob@ortho.com"},
        )
        record = json.loads(app_env.read_text().strip())
        assert record["user_id"] == "bob@ortho.com"

    def test_input_file_hash_persisted(self, client, app_env):
        import hashlib
        content = _bmo_full()
        expected = hashlib.sha256(content).hexdigest()
        client.post("/bank-rec/reconcile-gl", files=_bmo_file(content))
        record = json.loads(app_env.read_text().strip())
        assert record["input_file_hash"] == expected

    def test_two_runs_form_hash_chain(self, client, app_env):
        client.post("/bank-rec/reconcile-gl", files=_bmo_file())
        client.post(
            "/bank-rec/reconcile-amex",
            files=_bmo_file(),
            data={"cutoff_date": "2026-03-05"},
        )
        records = [json.loads(l) for l in app_env.read_text().splitlines() if l.strip()]
        assert len(records) == 2
        assert records[1]["previous_run_hash"] == records[0]["run_hash"]
        assert records[0]["previous_run_hash"] == ""

    def test_get_runs_endpoint_returns_history(self, client, app_env):
        client.post("/bank-rec/reconcile-gl", files=_bmo_file())
        client.post(
            "/bank-rec/reconcile-amex",
            files=_bmo_file(),
            data={"cutoff_date": "2026-03-05"},
        )
        resp = client.get("/bank-rec/runs")
        assert resp.status_code == 200
        runs = resp.json()
        assert len(runs) == 2
        assert runs[0]["workflow"] == "RECONCILE_GL"
        assert runs[1]["workflow"] == "RECONCILE_AMEX"

    def test_audit_chain_cross_references_batch_records(self, client, app_env):
        """audit_chain in response must match audit_record_hashes in run log."""
        resp = client.post(
            "/bank-rec/reconcile-amex",
            files=_bmo_file(),
            data={"cutoff_date": "2026-03-05"},
        )
        response_chain = resp.json()["audit_chain"]
        record = json.loads(app_env.read_text().strip())
        assert record["audit_record_hashes"] == response_chain

    def test_run_hash_in_response_matches_log(self, client, app_env):
        resp = client.post("/bank-rec/reconcile-gl", files=_bmo_file())
        response_hash = resp.json()["run_hash"]
        record = json.loads(app_env.read_text().strip())
        assert record["run_hash"] == response_hash

    def test_duration_ms_recorded(self, client, app_env):
        client.post("/bank-rec/reconcile-gl", files=_bmo_file())
        record = json.loads(app_env.read_text().strip())
        assert record["duration_ms"] >= 0
