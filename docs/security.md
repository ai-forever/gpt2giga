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

Do not disclose suspected vulnerabilities in a public issue, discussion, or
pull request. Follow the repository
[security policy](https://github.com/krakenalt/gigaloom/blob/main/SECURITY.md)
and use
[GitHub private vulnerability reporting](https://github.com/krakenalt/gigaloom/security/advisories/new).
Provide a minimal redacted reproduction and never send credentials, user
content, native-home data, or raw provider traffic.

The primary security owner is
[`@krakenalt`](https://github.com/krakenalt). The backup maintainer role,
response targets, 2FA gate, and compromised-publisher recovery are defined in
the security and
[governance](https://github.com/krakenalt/gigaloom/blob/main/GOVERNANCE.md)
policies. Public cutover remains blocked until the distinct backup owner has
accepted access.
