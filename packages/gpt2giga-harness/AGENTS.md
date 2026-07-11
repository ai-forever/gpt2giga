# AGENTS.md — packages/gpt2giga-harness/

## Package Identity

- **Distribution:** `gpt2giga-harness==0.0.1`
- **Python namespace:** `gpt2giga_harness`
- **Commands:** `giga`, `gpt2giga-harness`
- **Dependency direction:** Harness may import reviewed gateway contracts;
  gateway code must not import Harness.

## Setup and Checks

Run workspace commands from the repository root:

```bash
uv sync --all-packages --all-extras --dev
uv run giga doctor
uv run pytest tests/harness -q
uv run ruff check packages/gpt2giga-harness/src/gpt2giga_harness tests/harness
uv run ruff format --check packages/gpt2giga-harness/src/gpt2giga_harness tests/harness
uv build --package gpt2giga-harness --no-sources
```

## Boundaries and Compatibility

- Keep all Harness imports under `gpt2giga_harness.*`; do not restore the old
  `gpt2giga.harness.*` namespace or add a broad compatibility shim.
- Keep the plugin entry-point group named `gpt2giga.harnesses`, with targets in
  `gpt2giga_harness.*`.
- The initial package depends on exactly `gpt2giga==0.2.2a1`. Do not widen the
  range without installed-artifact compatibility evidence.
- Reviewed gateway imports are `gpt2giga.protocols.normalized` and
  `from gpt2giga import run` for optional local sidecar startup.
- Preserve `~/.gpt2giga/harness`, project `.giga/` state, SQLite migrations,
  JSON/JSONL records, worktrees, managed homes, and approval semantics.
- Keep `ui/assets/**` in the no-build HTML/CSS/JavaScript stack and verify that
  those files remain packaged.

## Package Map

| Path | Purpose |
|---|---|
| `src/gpt2giga_harness/cli.py` | `giga` and `gpt2giga-harness` CLI |
| `src/gpt2giga_harness/harnesses/` | Built-in direct and external CLI adapters |
| `src/gpt2giga_harness/runtime/` | Durable jobs, workers, leases, policy, approvals |
| `src/gpt2giga_harness/sessions/` | Session and event persistence |
| `src/gpt2giga_harness/ui/` | FastAPI control plane and packaged no-build UI |
| `src/gpt2giga_harness/tools/` | Harness-owned tool and managed-secret contracts |
| `tests/harness/` | Harness and cross-package integration tests |

## Definition of Done

For a Harness-only change, run the focused Harness gate above. Before release
or after package-boundary changes, also run the root coverage gate, both member
builds, package-isolation tests, and the Docusaurus build.
