# AGENTS.md — GitHub automation

## Scope

These rules apply to `.github/**` in addition to the root instructions.
Workflow files are executable release and security configuration: preserve
their behavior deliberately and verify claims against the YAML itself.

## Invariants

- Keep the CI Python matrix aligned with both package `requires-python`
  declarations. CI must continue to run Ruff check, Ruff format check, pytest
  coverage, both member builds, and installed-artifact smoke checks.
- Keep the production Docker image gateway-only. Harness commands, namespace,
  dependencies, and UI assets must not enter `Dockerfile` or Docker workflows.
- Treat `publish-pypi.yml` package selection, tag filters, attestations, and
  manual-dispatch behavior as release policy. Do not widen publishing scope or
  trigger a release as part of validation.
- Minimize `permissions:`; never expose secrets to untrusted pull-request code
  or print secret values.
- Keep action versions explicit. Review third-party actions and permission
  changes as supply-chain-sensitive code.

## Coupled changes

- Keep `ci.yaml`, `scripts/generate_badge.py`, coverage artifact names, and
  `badges/coverage.svg` expectations aligned.
- Keep `docker_image.yaml`, `publish-ghcr.yml`, `docker-smoke.yaml`, the
  Dockerfile, and documented tag/health semantics aligned.
- Keep `docs-pages.yaml`, `docs-site/package-lock.json`, and Docusaurus
  commands aligned.
- Keep English and Russian PR/issue templates structurally aligned.
- When workspace paths or package boundaries change, audit every workflow path
  filter, build command, cache key, and artifact assertion.

## Validation

- Run the exact local commands represented by a changed workflow when feasible.
- Run `actionlint` if it is installed; otherwise inspect the complete workflow
  diff and rely on repository contract tests plus GitHub validation.
- For release or packaging changes, run the full root quality gate, both
  `--no-sources` package builds, and the relevant package-isolation tests.
- For docs workflow changes, run `npm --prefix docs-site run build`.
