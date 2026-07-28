# Security

GigaLoom treats local execution, stored evidence, credentials, network access,
and remote-service mutations as separate trust boundaries.

## Safety model

- Provider credentials stay in provider-owned homes or explicit secret
  resolution boundaries.
- Secrets are redacted before persistence, logs, diagnostics, previews, and UI
  responses.
- Content capture is opt-in.
- Mutating actions require scoped authority where policy demands it.
- Approval binds the exact scope and preview; dispatch revalidates both.
- External commands use explicit arguments, controlled working directories,
  bounded output, and redacted records.
- Network and GitHub capabilities fail closed unless an exact grant exists.

Do not commit credentials, tokens, `.env` values, certificates, raw traffic, or
secret-bearing fixtures.

## Reporting vulnerabilities

Until the repository security policy is established in the next governance
slice, do not disclose suspected vulnerabilities in a public issue. Contact the
repository owner privately through their verified GitHub profile and provide a
minimal redacted reproduction. S3-04 will establish the durable policy and
supported reporting channel.

This page describes product behavior; it does not claim that external
governance or private reporting infrastructure is already configured.
