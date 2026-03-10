# Sentient Ledger MCP Servers

Six [Model Context Protocol](https://modelcontextprotocol.io) (MCP) servers that expose external systems as tools callable by Sentient Ledger agents.

## Architecture

```
Agent  ──▶  Orchestrator  ──▶  MCP Server  ──▶  External System
                │
                └──▶  Fallback (file ingest)  on server failure
```

The **orchestrator** (`orchestrator.py`) is the single entry point.  It routes `MCPToolCall` objects to the correct server, logs every interaction as a `SystemConnectionLog` entry, and supports graceful fallback to the file-ingest pipeline when a live API is unavailable.

## Servers

| Server | File | External System | Auth |
|--------|------|-----------------|------|
| `filesystem` | `file_system_server.py` | Network drive (N:\\ / /Volumes/Network) | None |
| `bc` | `bc_server.py` | Business Central REST API | OAuth 2.0 via Azure AD |
| `concur` | `concur_server.py` | SAP Concur REST API | OAuth 2.0 refresh token |
| `avalara` | `avalara_server.py` | Avalara AvaTax REST API | HTTP Basic (account/license) |
| `tango` | `tango_server.py` | Tango Card RaaS API | HTTP Basic (platform credentials) |
| `bmo` | `bmo_server.py` | BMO CSV download (no public API) | None |

## Quick Start

```python
from sentient_ledger.models.mcp import MCPToolCall
from sentient_ledger.mcp_servers import call_tool

result = call_tool(MCPToolCall(
    server_name="bmo",
    tool_name="parse_bmo_csv",
    arguments={"csv_content": csv_string},
))
print(result.data)  # {"headers": [...], "rows": [...], ...}
```

### Fallback pattern

```python
from sentient_ledger.mcp_servers import call_tool_with_fallback

result = call_tool_with_fallback(
    MCPToolCall(server_name="bc", tool_name="get_trial_balance", arguments={"company": "ortho"}),
    fallback_fn=ingest_trial_balance_from_file,
    fallback_kwargs={"path": "/n/path/to/tb.csv"},
)
```

### Health check

```python
from sentient_ledger.mcp_servers import health_check_all

statuses = health_check_all()
for s in statuses:
    print(s.server_name, "✓" if s.healthy else "✗", s.latency_ms, "ms")
```

## Environment Variables

Copy `.env.example` to `.env` and fill in your credentials:

```
BC_TENANT_ID=<azure-tenant-id>
BC_CLIENT_ID=<azure-app-client-id>
BC_CLIENT_SECRET=<azure-app-client-secret>
BC_BASE_URL=https://api.businesscentral.dynamics.com/v2.0
BC_ENVIRONMENT=production
BC_COMPANY_ID_ORTHO=<ortho-company-guid>
BC_COMPANY_ID_UTZY=<utzy-company-guid>

CONCUR_CLIENT_ID=...
CONCUR_CLIENT_SECRET=...
CONCUR_REFRESH_TOKEN=...

AVALARA_ACCOUNT_ID=...
AVALARA_LICENSE_KEY=...
AVALARA_COMPANY_CODE=OMPI

TANGO_PLATFORM_NAME=...
TANGO_PLATFORM_KEY=...
TANGO_ACCOUNT_ID=...
TANGO_CUSTOMER_ID=...

FS_DRIVE_ROOT=N:\
```

## Tool Reference

### `filesystem` server

| Tool | Description |
|------|-------------|
| `list_files(relative_dir, pattern)` | List files matching glob pattern |
| `read_csv(relative_path, max_rows)` | Read CSV → headers + rows |
| `read_excel(relative_path, sheet_name, max_rows)` | Read XLSX → headers + rows |
| `write_csv(relative_path, headers, rows)` | Write rows to CSV, create dirs |
| `file_exists(relative_path)` | Check existence + size |
| `get_latest_file(relative_dir, pattern)` | Most recently modified file |

### `bc` server

| Tool | Description |
|------|-------------|
| `get_companies()` | List accessible BC companies |
| `get_gl_entries(company, account_no, ...)` | Fetch G/L entries for an account |
| `get_bank_account_balance(company, bank_account_no)` | Current bank balance |
| `get_trial_balance(company, date_from, date_to)` | Trial balance by period |
| `get_fixed_assets(company, status)` | Fixed asset register |
| `post_bank_rec_lines(company, bank_account_no, lines)` | Post bank rec (balance-zero guard) |
| `post_journal_entries(company, journal_batch, lines)` | Post cash receipt journal |
| `health_check_bc()` | Connectivity check |

### `concur` server

| Tool | Description |
|------|-------------|
| `get_expense_reports(pay_group, status, limit)` | Fetch expense reports |
| `approve_expense_report(report_id, comment)` | Approve a report |
| `get_payment_batches(pay_group, status)` | Payment batch status |
| `get_employees(pay_group, limit)` | List employees by pay group |
| `health_check_concur()` | Connectivity check |

### `avalara` server

| Tool | Description |
|------|-------------|
| `calculate_tax(amount, ship_from_state, ship_to_state, ...)` | Calculate sales tax |
| `commit_transaction(transaction_code)` | Lock transaction for reporting |
| `list_nexus(country)` | Registered nexus jurisdictions |
| `get_filing_calendar(year, month)` | Tax filing calendar |
| `check_combined_filing_states(states)` | Flag combined-filing states |
| `health_check_avalara()` | Connectivity check |

### `tango` server

| Tool | Description |
|------|-------------|
| `list_catalog(country_code, currency_code)` | Available reward brands |
| `get_account_balance()` | Current Tango account balance |
| `validate_brand(brand_name)` | Check approved-brand list (local, no API call) |
| `place_order(brand_name, utid, amount, ...)` | Place reward (approved brands only) |
| `get_order_status(order_id)` | Order delivery status |
| `health_check_tango()` | Connectivity check |

### `bmo` server

| Tool | Description |
|------|-------------|
| `parse_bmo_csv(csv_content)` | Parse raw CSV → structured rows |
| `classify_transactions(csv_content)` | Add vendor_category to each row |
| `get_unreconciled_transactions(csv_content)` | Filter to rows with no Bank Rec # |
| `get_amex_transactions(csv_content, cutoff_date)` | Filter to AMEX rows |

## Security Notes

- **No hardcoded credentials** anywhere in this codebase.
- All secrets are read from environment variables at call time.
- The `filesystem` server enforces a drive-root jail — no path can escape `FS_DRIVE_ROOT`.
- `tango.place_order` enforces the `TANGO_APPROVED_BRANDS` allowlist before making any API call.
- `bc.post_bank_rec_lines` enforces balance-zero before posting to BC.
