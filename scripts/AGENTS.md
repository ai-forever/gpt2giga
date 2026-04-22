# AGENTS.md — scripts/

## Package Identity

- **What:** Small helper scripts for CI and local debugging
- **Current contents:** Coverage badge generation, mitmproxy SSE capture, and maintainer-only internal utilities

## Files

| File | Purpose |
|---|---|
| `scripts/generate_badge.py` | Generate `badges/coverage.svg` from a numeric coverage percentage |
| `scripts/sse_event.py` | mitmproxy addon for inspecting SSE chunks and reconstructing streamed responses |
| `scripts/internal/count_python_lines.py` | Count physical Python lines in the repo, excluding junk/vendor/test folders |
| `scripts/internal/load_translate.py` | Load-test the `/translate` endpoint across provider-pair scenarios |
| `scripts/internal/make_clean_zip.py` | Build a clean distributable ZIP while excluding secrets, caches, and junk |

## Setup & Run

```bash
# Generate/update the coverage badge
uv run python scripts/generate_badge.py 87.5 badges/coverage.svg

# Use the mitmproxy addon manually
mitmproxy -s scripts/sse_event.py

# Count Python lines in the repo
uv run python scripts/internal/count_python_lines.py --sort path

# Exercise provider-to-provider translation locally
uv run python scripts/internal/load_translate.py --base-url http://localhost:8090

# Build a clean ZIP snapshot
uv run python scripts/internal/make_clean_zip.py
```

## Patterns & Conventions

- Keep scripts small, standalone, and safe for automation.
- Prefer stdlib-only implementations unless there is a strong reason not to.
- Scripts used by CI must stay non-interactive.
- Files under `scripts/internal/` may assume a maintainer/source-checkout workflow, but should still stay non-destructive by default.
- If workflow behavior depends on a script, update the matching workflow in `.github/workflows/` in the same change.

## Quick Find Commands

```bash
# Find workflow references to scripts
rg -n "scripts/" .github/workflows

# Find badge output references
rg -n "coverage.svg|generate_badge" .github/workflows README.md
```

## Common Gotchas

- `generate_badge.py` takes a numeric percentage, not a path to `coverage.json`; keep docs/workflows aligned with how CI calls it.
- `sse_event.py` depends on `mitmproxy` objects but `mitmproxy` is not a core project dependency; treat it as an optional debugging helper.
- `load_translate.py` targets `/translate` and assumes the local proxy is already running.
- `make_clean_zip.py` intentionally excludes `.env*` secrets while keeping `.env.example`-style templates unless explicitly disabled.

## Pre-PR Check

```bash
uv run ruff check scripts
uv run ruff format --check scripts
```
