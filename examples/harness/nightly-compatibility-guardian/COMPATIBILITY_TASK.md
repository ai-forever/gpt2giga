# Nightly compatibility contract

The guardian uses one reviewed matrix:

- adapters: `codex-cli`, `claude-code`, and `gemini-cli`;
- route: GigaChat API mode `v2`;
- model: `GigaChat-2-Max`;
- tasks: route/model identity and failure-taxonomy acknowledgement;
- workspace: read-only source plus a Harness-owned scheduled worktree.

Every eval run records adapter version and event-schema dimensions. Compare a
run only with a pinned baseline whose adapter dimensions match exactly.
Run `giga compatibility check --json` before the model-backed matrix so native
CLI, provider protocol, SDK/schema, and marketplace drift fails closed first.

Classify failed cells as exactly one of:

- `product`: Harness orchestration or its compatibility contract failed;
- `adapter`: native CLI or normalized event semantics drifted;
- `model`: execution was truthful, but the model missed the task contract;
- `environment`: proxy, credential, executable, network, or worker readiness
  prevented a valid run.

The schedule must pass `test-now` for its exact immutable hash before it can be
enabled. A later failed scheduled eval is therefore meaningful regression
evidence and moves the schedule into Attention without modifying the project.
