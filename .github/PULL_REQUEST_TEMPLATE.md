## Description

Fix pre-release compatibility and dependency hardening issues:

- Restore Python 3.10 compatibility in telemetry and request observability code.
- Ensure built-in observability sinks are registered before configured sink names are resolved.
- Update the locked `python-multipart` package from `0.0.26` to `0.0.29`.

## Motivation

This keeps the pre-release branch compatible with the supported Python 3.10-3.14 range and addresses a vulnerable multipart dependency before release.

Closes: N/A

## Type of Change

- [x] Bug fix (non-breaking change that fixes an issue)
- [ ] New feature (non-breaking change that adds functionality)
- [ ] Breaking change (fix or feature that would cause existing functionality to not work as expected)
- [ ] Documentation update
- [ ] Code refactoring (no functional changes)
- [ ] Performance improvement
- [ ] Test coverage improvement
- [ ] CI/CD or tooling change

## Changes Made

- Replaced `datetime.UTC` imports with `datetime.timezone.utc` aliases in telemetry, observability middleware, and affected tests so imports work on Python 3.10.
- Added lazy built-in sink registration before observability hub creation resolves sink names.
- Refreshed the `uv.lock` entry for `python-multipart` to `0.0.29`.

## Testing

Ran the full local quality gate and package build.

### Test Coverage

- [x] Unit tests added/updated
- [ ] Integration tests added/updated (if applicable)
- [x] All existing tests pass locally

### Manual Testing

No manual API exercise was needed for this compatibility and dependency-maintenance change.

#### Method Used

- [ ] OpenAI Python SDK
- [ ] curl
- [ ] Docker
- [x] Other: automated local quality gate and package build

<details>
<summary>Test commands / code</summary>

```bash
uv run ruff check .
uv run ruff format --check .
uv run pytest tests/ --cov=. --cov-fail-under=80
uv build
```

Results:

- `uv run ruff check .`: passed
- `uv run ruff format --check .`: passed, 377 files already formatted
- `uv run pytest tests/ --cov=. --cov-fail-under=80`: 745 passed, 2 skipped, 23 warnings; total coverage 85.68%
- `uv build`: built `dist/gpt2giga-1.0.0rc3.tar.gz` and `dist/gpt2giga-1.0.0rc3-py3-none-any.whl`

</details>

## Checklist

### Code Quality

- [x] Code follows the project's style guidelines
- [x] I have performed a self-review of my code
- [x] I have commented my code, particularly in hard-to-understand areas
- [x] Ruff lint passes (`uv run ruff check .`)
- [x] Ruff format check passes (`uv run ruff format --check .`)
- [x] All tests pass (`uv run pytest tests/ --cov=. --cov-fail-under=80`)
- [x] Package build passes (`uv build`)

### Documentation

- [x] I have updated the documentation accordingly
- [x] Docstrings follow Google style with imperative mood
- [ ] I have added examples for new features (if applicable)
- [ ] README.md updated (if applicable)

### Dependencies

- [x] No new dependencies added
- [x] If dependencies added, they are justified and minimal
- [x] `uv.lock` updated (if dependencies changed)

### Compatibility

- [x] Changes are compatible with Python 3.10-3.14
- [x] Async/sync variants both work correctly (if applicable)

### Commits

- [x] Commit messages are clear and follow conventional commits style
- [x] Commits are logically organized
- [x] No debug code or commented-out code left in

## Additional Context

No linked issue and no UI changes.

## Pre-merge Actions

- [ ] Changelog updated (if applicable)
- [x] Version bump considered (if applicable)
- [x] Release gate reviewed for version/docs/assets drift when applicable (see [docs/release-checklist.md](../docs/release-checklist.md))
