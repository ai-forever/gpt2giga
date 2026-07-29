# AGENTS.md — Harness package

## Scope and boundary

These rules apply to `packages/gpt2giga-harness/**` in addition to the root
contract.

- Keep Harness-owned imports under `gpt2giga_harness.*`. Do not restore the
  old `gpt2giga.harness.*` namespace or add a broad compatibility shim.
- Keep the plugin entry-point group `gpt2giga.harnesses`; entry-point targets
  belong in `gpt2giga_harness.*`.
- Keep the gateway dependency exact unless an explicit release change includes
  installed-artifact compatibility evidence.
- Reviewed gateway boundaries are normalized protocol models used by Direct
  Chat and `from gpt2giga import run` in optional sidecar startup. Do not add a
  new gateway import without proving the standalone package contract.

## Runtime invariants

- Preserve backward-compatible user state under `~/.gpt2giga/harness` and
  project `.giga/`: SQLite migrations, JSON/JSONL records, session metadata,
  worktrees, managed homes, approvals, and provenance.
- Redact before persistence and before API/UI serialization. Secret resolution
  may cross an explicit execution boundary but secret values must not appear in
  previews, records, logs, traces, diffs, or errors.
- Mutating actions must remain approval-gated where policy requires it.
  Worktree-mutating edit/apply flows must fail closed when isolation, approval,
  lease, or policy checks fail.
- Preserve idempotency, atomic writes, file locks, lease/cancellation semantics,
  and crash reconciliation when changing durable runtime flows.
- External commands must use explicit argv, controlled cwd/env, bounded output,
  and redacted records. Do not introduce `shell=True` or mutate a user's
  native Codex, Claude, or Gemini home.
- Keep Cockpit assets integrity-checked and available from installed artifacts.
  Do not add a second packaged UI or a new frontend build architecture without
  an explicit roadmap slice.

## Ownership guide

| Path under `src/gpt2giga_harness/` | Responsibility |
|---|---|
| `cli.py`, `doctor.py`, `config.py` | CLI, diagnostics, Harness configuration |
| `harnesses/`, `native/` | Built-in adapters and native session connectors |
| `runtime/`, `sessions/` | Durable jobs, policy, leases, attempts, stored events |
| `ui/` | FastAPI control plane, routers, security, packaged static UI |
| `tools/`, `mcp.py`, `managed_mcp.py` | Tool contracts, policy, managed secrets/config |
| `project*.py`, `workspace.py`, `worktrees.py` | Project state, bounded filesystem access, edit isolation |
| `workflows.py`, `schedules.py`, `evals.py`, `agents.py` | Higher-level orchestration and authoring |

Keep `ui/app.py` as composition; add cohesive API families to `ui/routers/`
instead of expanding the composition module. Use temporary data dirs and repos
in tests; never exercise real user state.

## Validation

Run from the repository root:

```bash
npm --prefix packages/gpt2giga-harness/frontend ci --ignore-scripts
npm --prefix packages/gpt2giga-harness/frontend run build
./scripts/ci-base.sh sync
./scripts/ci-base.sh ruff-check packages/gpt2giga-harness/src/gpt2giga_harness tests/harness
./scripts/ci-base.sh ruff-format-check packages/gpt2giga-harness/src/gpt2giga_harness tests/harness
./scripts/ci-base.sh pytest tests/harness -q
uv build --package gpt2giga-harness --no-sources
```

`uv run giga doctor` is an environment smoke check, not a hermetic quality
gate. For UI changes, also verify the packaged asset test and perform browser QA
at relevant desktop and mobile widths. For metadata, imports, package data, or
release changes, run the root coverage gate plus the standalone base-artifact
and locked public-gateway tests.
