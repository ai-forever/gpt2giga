# AGENTS.md — scripts/ (utility scripts)

## Package Identity

- **What:** Small maintenance scripts used by CI and local workflows
- **Primary use today:** Coverage badge generation for README (`badges/coverage.svg`)

## Setup & Run

```bash
# Run the badge generator (CI uses this pattern)
uv run python scripts/generate_badge.py 87.5 badges/coverage.svg
```

## Patterns & Conventions

- Keep scripts **pure and standalone** (stdlib only when possible).
- Prefer **simple CLI interfaces** (positional args) with clear usage in the module docstring.
- Scripts can be used by GitHub Actions; avoid interactive prompts.

Examples:

- ✅ DO: Follow the style of `scripts/generate_badge.py` (small, documented CLI)
- ✅ DO: Keep CI wiring in `.github/workflows/ci.yaml`
- ❌ DON'T: Make scripts depend on `local/` artifacts (e.g. `local/gigachat-0.1.43-py3-none-any.whl`)
- ❌ DON'T: Require network access from scripts run in CI (keep CI stable)

## Touch Points / Key Files

- **Coverage badge generator**: `scripts/generate_badge.py`
- **CI job invoking script**: `.github/workflows/ci.yaml`
- **Badge output location**: `badges/coverage.svg`

## JIT Index Hints

```bash
# Find script invocations from workflows
rg -n "scripts/generate_badge\\.py|badges/coverage\\.svg" .github/workflows/
```

## Common Gotchas

- CI passes coverage as a number; keep the script tolerant of floats (see `.github/workflows/ci.yaml` badge step).

## Pre-PR Checks

```bash
uv run ruff check scripts/ && uv run ruff format --check scripts/
```

