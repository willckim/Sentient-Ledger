"""Unit tests for file_system_server MCP tools."""

from __future__ import annotations

import csv
import io
from pathlib import Path

import pytest


@pytest.fixture()
def drive_root(tmp_path, monkeypatch):
    """Point FS_DRIVE_ROOT at a temp directory."""
    monkeypatch.setenv("FS_DRIVE_ROOT", str(tmp_path))
    return tmp_path


def _write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        path.write_text("")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


class TestListFiles:
    def test_empty_directory(self, drive_root):
        from sentient_ledger.mcp_servers.file_system_server import list_files
        result = list_files("")
        assert result["count"] == 0
        assert result["files"] == []

    def test_finds_csv_files(self, drive_root):
        (drive_root / "a.csv").write_text("x")
        (drive_root / "b.csv").write_text("y")
        from sentient_ledger.mcp_servers.file_system_server import list_files
        result = list_files("", pattern="*.csv")
        assert result["count"] == 2

    def test_pattern_filters(self, drive_root):
        (drive_root / "data.csv").write_text("x")
        (drive_root / "notes.txt").write_text("y")
        from sentient_ledger.mcp_servers.file_system_server import list_files
        result = list_files("", pattern="*.csv")
        assert result["count"] == 1
        assert result["files"][0].endswith("data.csv")

    def test_nonexistent_directory(self, drive_root):
        from sentient_ledger.mcp_servers.file_system_server import list_files
        result = list_files("nonexistent/subdir")
        assert "error" in result


class TestReadCsv:
    def test_reads_csv_rows(self, drive_root):
        path = drive_root / "test.csv"
        _write_csv(path, [{"name": "Alice", "age": "30"}, {"name": "Bob", "age": "25"}])
        from sentient_ledger.mcp_servers.file_system_server import read_csv
        result = read_csv("test.csv")
        assert result["total_rows"] == 2
        assert result["headers"] == ["name", "age"]
        assert result["rows"][0]["name"] == "Alice"

    def test_missing_file_returns_error(self, drive_root):
        from sentient_ledger.mcp_servers.file_system_server import read_csv
        result = read_csv("missing.csv")
        assert "error" in result

    def test_max_rows_respected(self, drive_root):
        path = drive_root / "big.csv"
        _write_csv(path, [{"x": str(i)} for i in range(100)])
        from sentient_ledger.mcp_servers.file_system_server import read_csv
        result = read_csv("big.csv", max_rows=10)
        assert result["total_rows"] == 10


class TestWriteCsv:
    def test_creates_file_and_writes_rows(self, drive_root):
        from sentient_ledger.mcp_servers.file_system_server import write_csv
        result = write_csv(
            "output/data.csv",
            headers=["a", "b"],
            rows=[{"a": "1", "b": "2"}, {"a": "3", "b": "4"}],
        )
        assert result["written_rows"] == 2
        assert (drive_root / "output" / "data.csv").exists()

    def test_creates_parent_dirs(self, drive_root):
        from sentient_ledger.mcp_servers.file_system_server import write_csv
        write_csv("deep/nested/file.csv", headers=["x"], rows=[{"x": "1"}])
        assert (drive_root / "deep" / "nested" / "file.csv").exists()

    def test_extra_keys_ignored(self, drive_root):
        from sentient_ledger.mcp_servers.file_system_server import write_csv
        result = write_csv(
            "out.csv",
            headers=["a"],
            rows=[{"a": "1", "z": "ignored"}],
        )
        assert result["written_rows"] == 1


class TestFileExists:
    def test_existing_file_returns_true(self, drive_root):
        (drive_root / "exists.csv").write_text("data")
        from sentient_ledger.mcp_servers.file_system_server import file_exists
        result = file_exists("exists.csv")
        assert result["exists"] is True
        assert result["size_bytes"] > 0

    def test_missing_file_returns_false(self, drive_root):
        from sentient_ledger.mcp_servers.file_system_server import file_exists
        result = file_exists("missing.csv")
        assert result["exists"] is False
        assert result["size_bytes"] == 0


class TestGetLatestFile:
    def test_returns_most_recent(self, drive_root, tmp_path):
        import time
        (drive_root / "old.csv").write_text("old")
        time.sleep(0.01)
        (drive_root / "new.csv").write_text("new")
        from sentient_ledger.mcp_servers.file_system_server import get_latest_file
        result = get_latest_file("", pattern="*.csv")
        assert result["path"].endswith("new.csv")

    def test_empty_directory_returns_empty_path(self, drive_root):
        from sentient_ledger.mcp_servers.file_system_server import get_latest_file
        result = get_latest_file("")
        assert result["path"] == ""

    def test_nonexistent_dir_returns_error(self, drive_root):
        from sentient_ledger.mcp_servers.file_system_server import get_latest_file
        result = get_latest_file("no_such_dir")
        assert "error" in result
