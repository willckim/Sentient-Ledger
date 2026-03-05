"""RunRecord model and RunLogger — tamper-evident JSONL run history.

Every API call produces one RunRecord that is appended to runs.jsonl.
Each record contains a SHA-256 hash of the previous record (previous_run_hash),
forming a separate hash chain that runs parallel to the per-batch proposal audit
chain.  The audit_record_hashes field cross-references the batch chain.

Design constraints:
- Append-only JSONL: one JSON object per line, no seek/rewrite needed.
- Hash chain: previous_run_hash links records chronologically.
- No in-process cache: RunLogger reads the last line of the file to get the
  previous hash.  Safe for single-process deployments; for multi-process, add
  a file lock or migrate to SQLite.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from pathlib import Path

from pydantic import BaseModel

from sentient_ledger.agents.base import now_iso
from sentient_ledger.models.enums import BankRecWorkflow


class RunRecord(BaseModel):
    """Metadata record for a single API-triggered workflow run."""

    run_id: str
    workflow: BankRecWorkflow
    timestamp: str
    user_id: str

    input_file_name: str | None = None
    input_file_hash: str
    output_file_hash: str | None = None

    status: str  # "ok" | "warning" | "error"
    error_count: int = 0
    warning_count: int = 0
    new_rows: int = 0
    total_rows: int = 0

    # Cross-reference into the per-batch proposal audit chain
    audit_record_hashes: list[str] = []

    duration_ms: int = 0

    # Hash chain fields — populated by RunLogger.log(), not by the caller
    previous_run_hash: str = ""
    run_hash: str = ""

    def compute_hash(self) -> str:
        """SHA-256 of all fields except run_hash itself."""
        data = self.model_dump(exclude={"run_hash"})
        raw = json.dumps(data, sort_keys=True, default=str)
        return hashlib.sha256(raw.encode()).hexdigest()


class RunLogger:
    """Appends RunRecords to a JSONL file and maintains the hash chain."""

    def __init__(self, log_path: Path) -> None:
        self.log_path = Path(log_path)

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def log(self, record: RunRecord) -> RunRecord:
        """Set previous_run_hash and run_hash, append to file, return logged record."""
        record = record.model_copy(
            update={"previous_run_hash": self._get_previous_hash()}
        )
        record = record.model_copy(update={"run_hash": record.compute_hash()})
        self._append(record)
        return record

    def read_all(self) -> list[RunRecord]:
        """Return all RunRecords in chronological order."""
        if not self.log_path.exists():
            return []
        records: list[RunRecord] = []
        for line in self.log_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                records.append(RunRecord.model_validate_json(line))
        return records

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _get_previous_hash(self) -> str:
        """Return run_hash of the last persisted record, or '' for the first."""
        if not self.log_path.exists():
            return ""
        last_line = ""
        for line in self.log_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                last_line = line.strip()
        if not last_line:
            return ""
        try:
            return json.loads(last_line).get("run_hash", "")
        except json.JSONDecodeError:
            return ""

    def _append(self, record: RunRecord) -> None:
        """Atomically append one JSON line to the log file."""
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.log_path.open("a", encoding="utf-8") as f:
            f.write(record.model_dump_json() + "\n")


def new_run_id() -> str:
    return str(uuid.uuid4())
