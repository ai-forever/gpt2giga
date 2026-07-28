# AGENTS.md — GitHub automation

## Scope

These rules apply to `.github/**` in addition to the root instructions.
Workflow files are executable release and security configuration: preserve
their behavior deliberately and verify claims against the YAML itself.

## Invariants

- Keep the CI Python matrix aligned with the Harness `requires-python`
  declaration. Required checks must keep Python 3.10, 3.13, and 3.14 Harness
  tests, Ruff, frontend, base artifact, terminal, performance, and browser QA
  independently visible.
- No quality job may rely on a gateway source tree, editable sibling, project
  lock, real provider, native user home, or mutable external service.
- Keep public registry/all-extras readiness explicitly
  `blocked_pending_S5_03B`. Candidate compatibility accepts only an explicit
  HTTPS wheel whose approved SHA-256 is checked before installation.
- Publication remains absent until its roadmap-owned release slice. Quality
  workflows must not push, publish, write badges, or broaden repository
  permissions.
- Minimize `permissions:`; never expose secrets to untrusted pull-request code
  or print secret values.
- Keep action versions explicit. Review third-party actions and permission
  changes as supply-chain-sensitive code.

## Coupled changes

- Keep `ci.yaml`, `nightly-smoke.yaml`, `scripts/ci-*.sh`, and their stable
  check and artifact names aligned.
- Keep `docs-pages.yaml`, `docs-site/package-lock.json`, and Docusaurus
  commands aligned.
- Keep English and Russian PR/issue templates structurally aligned.
- When workspace paths or package boundaries change, audit every workflow path
  filter, build command, cache key, and artifact assertion.

## Validation

- Run the exact local commands represented by a changed workflow when feasible.
- Run `actionlint` if it is installed; otherwise inspect the complete workflow
  diff and rely on repository contract tests plus GitHub validation.
- For packaging changes, run the full Harness quality gate, the standalone
  `--no-sources` build, and the relevant package-isolation tests.
- For docs workflow changes, run `npm --prefix docs-site run build`.
