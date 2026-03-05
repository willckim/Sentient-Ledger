"""API settings — read from environment variables, no module-level singletons."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Settings:
    runs_log_path: Path = field(default_factory=lambda: Path("logs/runs.jsonl"))

    @classmethod
    def from_env(cls) -> "Settings":
        """Create Settings by reading environment variables.

        Called once per request (inside dependency functions), never at module level.
        Keeps the config hot-reloadable and testable via monkeypatching.
        """
        log_path = os.getenv("SENTIENT_LEDGER_RUNS_LOG", "logs/runs.jsonl")
        return cls(runs_log_path=Path(log_path))
