# Security Policy

## Reporting a Vulnerability

If you discover a security vulnerability in Sentient Ledger, **do not open a public issue.**

Instead, please report it privately:

1. Go to the **Security** tab of this repository on GitHub.
2. Click **"Report a vulnerability"** to open a private security advisory.

If private advisories are not available on the repository, email the maintainer directly through their GitHub profile.

## What to Include

- Description of the vulnerability
- Steps to reproduce
- Affected component (e.g., envelope verification, audit chain, ingestion pipeline)
- Potential impact

## Response

- Acknowledgment within **48 hours**
- Fix or mitigation plan within **7 days** for critical issues
- Credit in the release notes unless you prefer to remain anonymous

## Scope

This policy covers the Sentient Ledger codebase, including:

- State envelope checksum verification
- Audit record hash-chain integrity
- Authority and SLA enforcement logic
- Ingestion pipeline input validation
- Any path that processes financial data
