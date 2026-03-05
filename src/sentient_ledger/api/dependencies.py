"""FastAPI dependency functions.

Authentication placeholder
--------------------------
``get_current_user`` currently extracts the optional ``X-User-ID`` request
header and returns its value (or "anonymous").  It does **not** verify any
token — that is intentional; auth is explicitly out of scope for this iteration.

To add authentication later, replace the body of ``get_current_user`` with
any verification logic (OAuth2 Bearer token, API key, JWT decode, etc.).
All four workflow endpoints already receive ``user_id`` via
``Depends(get_current_user)``, so they will automatically gain auth with
**zero changes** to route code.  This is the FastAPI dependency injection
contract.

Example future body:
    payload = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
    return payload["sub"]

Run logger
----------
``get_run_logger`` creates a fresh ``RunLogger`` per request, reading the
log path from the environment variable ``SENTIENT_LEDGER_RUNS_LOG``.
No module-level singleton — safe to monkeypatch in tests.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Header

from sentient_ledger.api.run_logger import RunLogger
from sentient_ledger.api.settings import Settings


def get_current_user(
    x_user_id: Annotated[str | None, Header()] = None,
) -> str:
    """Return the caller's identity from the X-User-ID header.

    Currently unauthenticated — returns the header value as-is, defaulting
    to "anonymous" when the header is absent.

    **To add authentication:** replace this function body with token
    verification logic.  The function signature must remain the same so
    FastAPI can inject it into all endpoint signatures unchanged.
    """
    return x_user_id or "anonymous"


def get_run_logger() -> RunLogger:
    """Create a RunLogger pointed at the configured JSONL log file.

    Reads ``SENTIENT_LEDGER_RUNS_LOG`` from the environment on every call,
    making it trivially testable via ``monkeypatch.setenv``.
    """
    settings = Settings.from_env()
    return RunLogger(settings.runs_log_path)
