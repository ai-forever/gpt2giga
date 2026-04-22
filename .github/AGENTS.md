# AGENTS.md — .github/

## Package Identity

- **What:** GitHub Actions workflows plus PR and issue templates
- **Scope:** CI, security automation, coverage badge generation, Docker publishing, PyPI release publishing, release drafting, triage automation

## Local Validation

```bash
uv sync --all-extras --dev
uv run ruff check .
uv run ruff format --check .
uv run pytest tests/ --cov=. --cov-fail-under=80
uv build
(cd packages/gpt2giga-ui && uv build --out-dir ../../dist)
```

## Workflow Map

| File | Purpose |
|---|---|
| `.github/workflows/ci.yaml` | Frontend checks, Ruff, packaging, and pytest across Python `3.10`–`3.14`, then regenerates the coverage badge |
| `.github/workflows/docker_image.yaml` | Publishes Docker Hub images for Python `3.10`–`3.14` |
| `.github/workflows/publish-ghcr.yml` | Publishes GHCR images for Python `3.10`–`3.14`; `latest` tracks Python `3.13` |
| `.github/workflows/publish-pypi.yml` | Builds with `uv` and publishes to PyPI on release |
| `.github/workflows/stale-issues.yaml` | Marks inactive issues as stale and closes them after a grace period |
| `.github/workflows/dependency-review.yaml` | Reviews dependency changes on pull requests |
| `.github/workflows/actionlint.yaml` | Lints GitHub Actions workflow files |
| `.github/workflows/codeql.yaml` | Runs weekly and on-change CodeQL analysis for Python |
| `.github/workflows/pip-audit.yaml` | Audits installed Python dependencies for known vulnerabilities |
| `.github/workflows/nightly-smoke.yaml` | Runs scheduled app-level smoke tests against the FastAPI app factory |
| `.github/workflows/docker-smoke.yaml` | Builds the default Docker image and verifies `/health` comes up |
| `.github/workflows/pr-labeler.yaml` | Applies path-based labels to pull requests |
| `.github/workflows/release-drafter.yaml` | Keeps the draft GitHub release notes up to date |
| `.github/dependabot.yml` | Weekly Dependabot updates for GitHub Actions dependencies |
| `.github/labeler.yml` | Path-to-label mapping for provider surfaces, shared runtime/features, admin/UI, docs/examples, tests, and delivery assets |
| `.github/release-drafter.yml` | Release note categories aligned with the PR labels above |
| `.github/PULL_REQUEST_TEMPLATE.md` | PR checklist |
| `.github/ISSUE_TEMPLATE/bug_report.md` | Bug report template |

## Patterns & Conventions

- Keep CI aligned with the root Definition of Done.
- Preserve the Python compatibility matrix unless the package support policy changes too.
- Use GitHub secrets only where required; never inline credentials in workflow YAML.
- Badge generation depends on both `.github/workflows/ci.yaml` and `scripts/generate_badge.py`; change them together.
- `publish-pypi.yml` validates that the release tag matches `pyproject.toml` version; keep that contract intact.
- CI and scheduled Python workflows should use `astral-sh/setup-uv` with `python-version` instead of relying on a separate `uv python install` step.
- `actions/labeler` expects labels referenced in `.github/labeler.yml` to exist in the repository settings; this repo does not auto-create them.
- Keep `.github/labeler.yml` and `.github/release-drafter.yml` in sync. The current label set is `openai`, `anthropic`, `gemini`, `translate`, `admin`, `frontend`, `features`, `providers`, `runtime`, `docker`, `ci`, `docs`, `examples`, `tests`, and `dependencies`.

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

- `ci.yaml` downloads the `coverage-3.13` artifact to generate the badge; if artifact naming changes, update both steps.
- `docker_image.yaml` and `publish-ghcr.yml` both build multi-arch images; keep version tagging consistent with `pyproject.toml`.
- `publish-pypi.yml` clears `dist/` before build, so release packaging assumptions should not rely on checked-in artifacts.

## Pre-PR Check

```bash
uv run ruff check .
uv run ruff format --check .
uv run pytest tests/ --cov=. --cov-fail-under=80
uv build
(cd packages/gpt2giga-ui && uv build --out-dir ../../dist)
```
