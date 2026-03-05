"""FastAPI application factory.

Usage
-----
Development server (requires uvicorn in [server] optional deps):

    uvicorn sentient_ledger.api.app:app --reload

Production:

    uvicorn sentient_ledger.api.app:app --host 0.0.0.0 --port 8000 --workers 4

Testing:

    from sentient_ledger.api.app import create_app
    app = create_app()
    client = TestClient(app)

``create_app()`` is a factory so each test gets an isolated app instance.
The module-level ``app`` object lets uvicorn import it directly.
"""

from __future__ import annotations

from fastapi import FastAPI

from sentient_ledger.api.routes import bank_rec as bank_rec_routes


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    application = FastAPI(
        title="Sentient Ledger API",
        description=(
            "Bank reconciliation workflow automation for Business Central. "
            "Triggers post_new_lines, reconcile_gl, reconcile_amex, and "
            "cash_receipt_journal workflows via HTTP POST; returns BC-ready "
            "import CSVs as base64 with full audit chain metadata."
        ),
        version="1.0.0",
        docs_url="/docs",
        redoc_url="/redoc",
    )

    # ---------------------------------------------------------------------------
    # Routers
    # ---------------------------------------------------------------------------
    application.include_router(
        bank_rec_routes.router,
        prefix="/bank-rec",
        tags=["Bank Reconciliation"],
    )

    # ---------------------------------------------------------------------------
    # Health check — no auth required, for load balancer / uptime monitoring
    # ---------------------------------------------------------------------------
    @application.get("/health", tags=["Meta"])
    def health() -> dict:
        """Return service liveness status."""
        return {"status": "ok", "version": "1.0.0"}

    return application


# Module-level app instance for uvicorn and any tooling that imports it.
# Tests should use create_app() instead to get isolated instances.
app = create_app()
