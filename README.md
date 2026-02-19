# Sentient Ledger

**Enterprise Agentic Audit Engine** for autonomous financial reconciliation. Ingests Dynamics 365 exports, validates ledger integrity through a multi-agent pipeline, and produces auditable adjustment proposals secured by SHA-256 hash-chain verification.

## Reliability

| Metric | Value |
|--------|-------|
| Test suite | **506 passing** (unit, integration, eval) |
| Critical scenario recall | **1.0** (12/12 critical scenarios detected) |
| Overall detection recall | **1.0** |
| Overall detection precision | **1.0** |
| Audit chain integrity | SHA-256 hash-chain, verified at every state transition |
| Envelope verification | Checksums computed and validated on all inter-agent messages |
| Arithmetic | `Decimal` throughout, never `float` |

## D365 Integration

End-to-end ingestion pipeline for Dynamics 365 Financial exports:

- **Trial Balance** — column mapping, debit/credit validation, account category heuristics
- **Fixed Asset Register** — enum translation (depreciation method, convention, status), computed fields, SHA-256 row hashes
- **Depreciation Schedule** — period validation, amount/accumulated/NBV consistency checks

CSV files are parsed, mapped to canonical Pydantic models, validated against configurable rules, and adapted for the detection engine. Malformed rows are counted and quarantined when they exceed the configured threshold.

## Pipeline

A 10-node LangGraph state machine orchestrates the reconciliation flow:

```
INGEST --> COMPLIANCE_SCAN --> ASSET_INSPECTION --> ANALYSIS --> PROPOSAL --> SIGN_OFF --> COMMIT --> AUDIT_LOG
                |                    |                                          |
                +--> ANALYSIS        +--> SELF_HEAL                            +--> PROPOSAL (rejection cycle)
                     (clean path)                                               +--> ERROR_QUARANTINE
```

Every state transition produces a `StateEnvelope` with a computed SHA-256 checksum. Every proposal generates an immutable audit record linked to the previous record by hash, forming an append-only chain from `CREATED` through `APPROVED` to `COMMITTED`.

## Key Properties

- **Authority enforcement** — config-driven thresholds (L1 Staff through L4 Controller) determine approval requirements based on adjustment magnitude
- **SLA monitoring** — deadlines computed per authority level; expiry triggers automatic escalation through a configurable escalation path
- **Envelope integrity** — tampered payloads are detected by checksum mismatch at any point in the pipeline
- **Observability** — optional `PipelineObserver` captures per-node timing, state key flow, and execution summary
- **Deterministic** — no LLM calls in the pipeline; all agent logic is pure-function, fully testable

## Stack

- Python 3.10+
- [LangGraph](https://github.com/langchain-ai/langgraph) — state machine orchestration
- [Pydantic v2](https://docs.pydantic.dev/) — typed domain models with validation
- pytest — 506 tests across unit, integration, and eval suites

## Setup

```bash
python -m venv .venv
source .venv/bin/activate   # .venv\Scripts\activate on Windows
pip install -e ".[dev]"
```

## Tests

```bash
python -m pytest tests/ -x -q              # full suite (506 tests)
python -m pytest tests/integration/ -v      # gate tests (P2-P5)
python -m pytest tests/eval/ -x -q          # 54 synthetic detection scenarios
```

## Security

See [SECURITY.md](SECURITY.md) for vulnerability reporting policy.

## License

GNU General Public License v3.0. See [LICENSE](LICENSE).
