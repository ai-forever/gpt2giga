# AGENTS.md — scripts

## Scope and rules

- Keep tracked scripts small, standalone, non-interactive, and safe for local or
  CI automation.
- Prefer the standard library. Do not add an application runtime dependency
  solely for a maintenance or debugging script.
- Keep CLI inputs explicit, validate them, return non-zero on failure, and avoid
  hidden network or filesystem side effects.
- Keep generated tracked output deterministic. A script that updates a badge or
  another artifact must produce stable output for the same input.
- Change a CI-used script together with every workflow that depends on its CLI,
  output path, or data format.
- Keep optional debugging imports such as mitmproxy out of package runtime code.
- `scripts/internal/` is ignored local tooling; do not edit, document as
  shipped, or force-add it unless the user explicitly puts it in scope.

## Validation

```bash
uv run ruff check scripts tests/test_scripts
uv run ruff format --check scripts tests/test_scripts
uv run pytest tests/test_scripts -q
```

Run a script-specific smoke only when it is hermetic. The examples smoke runner
requires a configured live proxy/upstream and is opt-in.
