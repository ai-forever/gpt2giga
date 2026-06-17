# AGENTS.md — scripts/

## Package Identity

- **What:** Small helper scripts for CI and local debugging
- **Current contents:** Coverage badge generation and mitmproxy SSE capture
- **Runtime role:** Not imported by the application package; keep scripts standalone

## Files

| File | Purpose |
|---|---|
| `scripts/generate_badge.py` | Generate `badges/coverage.svg` from a numeric coverage percentage |
| `scripts/run_examples_smoke.py` | Run runnable examples as a v1/v2 E2E smoke matrix against a local proxy |
| `scripts/sse_event.py` | mitmproxy addon for inspecting SSE chunks and reconstructing streamed responses |

## Setup & Run

```bash
# Generate/update the coverage badge
uv run python scripts/generate_badge.py 87.5 badges/coverage.svg

# Run runnable examples against a local proxy for both API versions
uv run python scripts/run_examples_smoke.py --api-versions v1,v2 -n 4

# Use the mitmproxy addon manually
mitmproxy -s scripts/sse_event.py
```

## Patterns & Conventions

- Keep scripts small, standalone, and safe for automation.
- Prefer stdlib-only implementations unless there is a strong reason not to.
- Scripts used by CI must stay non-interactive.
- If workflow behavior depends on a script, update the matching workflow in `.github/workflows/` in the same change.
- Do not add application runtime dependencies just for scripts; use optional/debug tooling where appropriate.
- Keep generated outputs deterministic when a script writes checked-in artifacts such as `badges/coverage.svg`.

## Quick Find Commands

```bash
# Find workflow references to scripts
rg -n "scripts/" .github/workflows

# Find badge output references
rg -n "coverage.svg|generate_badge" .github/workflows README.md

# Find mitmproxy/debug references
rg -n "mitmproxy|sse_event" .github deploy docs scripts
```

## Common Gotchas

- `generate_badge.py` takes a numeric percentage, not a path to `coverage.json`; keep docs/workflows aligned with how CI calls it.
- `ci.yaml` extracts `.totals.percent_covered` from `coverage.json` before calling `generate_badge.py`.
- `sse_event.py` depends on `mitmproxy` objects but `mitmproxy` is not a core project dependency; treat it as an optional debugging helper and avoid importing it from package code.

## Pre-PR Check

```bash
uv run ruff check scripts
uv run ruff format --check scripts
```
