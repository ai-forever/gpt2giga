# AGENTS.md — .github/

## Package Identity

- **What:** GitHub Actions workflows plus PR and issue templates
- **Scope:** CI, coverage badge generation, Docker publishing, PyPI release publishing, Codeflash automation

## Local Validation

```bash
uv sync --all-extras --dev
uv run ruff check .
uv run ruff format --check .
uv run pytest tests/ --cov=. --cov-fail-under=80
```

## Workflow Map

| File | Purpose |
|---|---|
| `.github/workflows/ci.yaml` | Ruff + pytest across Python `3.10`–`3.14`, uploads coverage, regenerates badge |
| `.github/workflows/docker_image.yaml` | Publishes Docker Hub images for Python `3.10`–`3.14` |
| `.github/workflows/publish-ghcr.yml` | Publishes GHCR images for Python `3.10`–`3.14`; `latest` tracks Python `3.13` |
| `.github/workflows/publish-pypi.yml` | Builds with `uv` and publishes to PyPI on release |
| `.github/workflows/codeflash.yaml` | Runs Codeflash optimization on PRs touching `gpt2giga/**` |
| `.github/workflows/stale-issues.yaml` | Marks inactive issues as stale and closes them after a grace period |
| `.github/PULL_REQUEST_TEMPLATE.md` | PR checklist |
| `.github/ISSUE_TEMPLATE/bug_report.md` | Bug report template |

## Patterns & Conventions

- Keep CI aligned with the root Definition of Done.
- Preserve the Python compatibility matrix unless the package support policy changes too.
- Use GitHub secrets only where required; never inline credentials in workflow YAML.
- Badge generation depends on both `.github/workflows/ci.yaml` and `scripts/generate_badge.py`; change them together.
- `publish-pypi.yml` validates that the release tag matches `pyproject.toml` version; keep that contract intact.
- `codeflash.yaml` currently uses `pip` and `poetry`, unlike the rest of the repo's `uv`-first tooling. Treat that as intentional unless you are updating the workflow itself.

## Quick Find Commands

```bash
# Find uv-based workflow steps
rg -n "uv sync|uv run|uv build|uv publish" .github/workflows

# Find Docker tag logic
rg -n "tags:|IMAGE_NAME|VERSION" .github/workflows

# Find coverage badge wiring
rg -n "coverage.json|generate_badge|coverage.svg" .github/workflows
```

## Common Gotchas

- `ci.yaml` downloads the `coverage-3.12` artifact to generate the badge; if artifact naming changes, update both steps.
- `docker_image.yaml` and `publish-ghcr.yml` both build multi-arch images; keep version tagging consistent with `pyproject.toml`.
- `publish-pypi.yml` clears `dist/` before build, so release packaging assumptions should not rely on checked-in artifacts.

## Pre-PR Check

```bash
uv run ruff check .
uv run ruff format --check .
uv run pytest tests/ --cov=. --cov-fail-under=80
```
