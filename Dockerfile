FROM python:3.10.11-slim AS base

# Reproducible builds — no .pyc files, unbuffered stdout
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install production dependencies first (layer-cached separately from source)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install uvicorn for the API server (declared as [server] optional dep)
RUN pip install --no-cache-dir "uvicorn[standard]==0.41.0"

# Install the package in editable mode
COPY pyproject.toml .
COPY src/ src/
RUN pip install --no-cache-dir -e .

# Non-root user for security
RUN useradd --create-home --no-log-init appuser
USER appuser

# Smoke-test the import on build (catches missing dep issues immediately)
RUN python -c "import sentient_ledger; print('import ok')"

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

CMD ["uvicorn", "sentient_ledger.api.app:app", \
     "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
