# Architecture

GigaLoom is a standalone Python distribution with three local surfaces:

1. the `giga` command dispatches provider-native commands and administrative
   operations;
2. the Textual terminal UI presents local runs and approvals;
3. the FastAPI control plane serves the packaged browser cockpit on loopback.

## Main boundaries

- `gpt2giga_harness.harnesses` owns built-in adapters.
- `runtime` and `sessions` own jobs, leases, events, policy, and persistence.
- `project`, `workspace`, and `worktrees` bound filesystem mutations.
- `ui` projects redacted state; it does not become a second authority source.
- native provider CLIs own authentication and provider-side execution.
- optional gateway behavior enters through an installed distribution contract,
  not a source-tree dependency.

Actions bind the reviewed scope and preview to an approval. Dispatch revalidates
that binding and fails closed after drift, cancellation, lease loss, or missing
authority. Sensitive values are redacted before persistence and serialization.

## Detailed decisions

- [Harness component architecture](architecture/harness.md)
- [Authority and approval schema](architecture/authority-approval-schema-adr.md)
- [Scoped network access](architecture/scoped-network-access-adr.md)
- [GitHub capability grants](architecture/github-capability-grants-adr.md)
- [Provider authentication matrix](architecture/provider-authentication-capability-matrix.md)
- [Frontend asset build](architecture/frontend-asset-build-architecture-adr.md)
- [Provider-native CLI facade](architecture/provider-native-cli-facade-adr.md)
