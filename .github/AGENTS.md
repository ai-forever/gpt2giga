# AGENTS.md — .github/ (CI/CD + templates)

## Package Identity

- **What:** GitHub Actions workflows + PR/issue templates for `gpt2giga`
- **Scope:** CI checks, Docker publishing, PyPI publishing, coverage badge automation

## Setup & Run

```bash
# Workflows run in GitHub Actions; locally you typically validate by running:
uv sync --all-extras --dev
uv run ruff check . && uv run ruff format --check .
uv run pytest tests/ --cov=. --cov-fail-under=80
```

## Patterns & Conventions

- **CI should match local DoD**: keep `.github/workflows/ci.yaml` aligned with root “Definition of Done”.
- **Keep secrets scoped**: publishing workflows must only use `secrets.*` where required.
- **Python matrix support**: CI tests on Python `3.10`–`3.14` (don’t add syntax that breaks older versions).

Examples:

- ✅ DO: Update the main CI steps in `.github/workflows/ci.yaml`
- ✅ DO: Update Docker publishing in `.github/workflows/publish-ghcr.yml` and `.github/workflows/docker_image.yaml`
- ❌ DON'T: Add repo secrets into workflow YAML (keep secrets in GitHub settings; compare with `.github/workflows/publish-pypi.yml`)
- ❌ DON'T: Treat scratch files as CI inputs (e.g. `local/concurrency_test.py`; CI is intended to validate `gpt2giga/` + `tests/` only)

## Touch Points / Key Files

- **CI (lint + tests + coverage)**: `.github/workflows/ci.yaml`
- **Docker Hub build/push**: `.github/workflows/docker_image.yaml`
- **GHCR multi-python images**: `.github/workflows/publish-ghcr.yml`
- **PyPI release publishing**: `.github/workflows/publish-pypi.yml`
- **Codeflash optimization**: `.github/workflows/codeflash.yaml`
- **PR checklist**: `.github/PULL_REQUEST_TEMPLATE.md`
- **Bug report template**: `.github/ISSUE_TEMPLATE/bug_report.md`

## JIT Index Hints

```bash
# Find uv/ruff/pytest invocations
rg -n "uv sync|uv run ruff|uv run pytest" .github/workflows/

# Find where Docker tags are defined
rg -n "tags:|IMAGE_NAME|VERSION=" .github/workflows/
```

## Common Gotchas

- `ci.yaml` generates a coverage badge and may commit `badges/coverage.svg` to the branch; if you change badge generation, update both the workflow and `scripts/generate_badge.py`.
- Publishing workflows are triggered by tags/releases; ensure version/tag expectations stay consistent with `pyproject.toml`.

## Pre-PR Checks

```bash
uv run ruff check . && uv run ruff format --check . && uv run pytest tests/ --cov=. --cov-fail-under=80
```

