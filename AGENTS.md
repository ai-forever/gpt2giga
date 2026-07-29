# AGENTS.md — Codex working contract

## Scope and precedence

- This file applies to the whole repository. A nearer `AGENTS.md` adds
  scope-specific rules and takes precedence when it conflicts with this file.
- Keep agent instructions decision-oriented. Do not duplicate exhaustive file,
  endpoint, workflow, or version inventories that can be read from source.
- Work from the repository root unless a command explicitly changes directory.
- Use `git ls-files` when mapping shipped code. Ignored bytecode and scratch
  artifacts can preserve obsolete directory layouts.

## Start every task

1. Run `git status --short` and preserve unrelated user changes.
2. Read the exact roadmap, issue, test, config, or artifact named by the user.
3. Find the owning code and its nearest tests before editing.
4. Make the smallest coherent change that satisfies the requested behavior.
5. Validate the changed layer first, then broaden validation in proportion to
   package, compatibility, security, or release risk.

Do not clean up adjacent code, regenerate unrelated artifacts, or rewrite user
work merely because it is present in the checkout.

## Repository contract

- This is the standalone GigaLoom repository and a one-member `uv` workspace.
- `packages/gpt2giga-harness/` owns the `gigaloom` distribution and
  `gpt2giga_harness` Python namespace.
- The base distribution must install, test, and build without a gateway source
  checkout.
- Optional gateway compatibility consumes only the exact public dependency
  resolved in the committed target `uv.lock`. Never add an editable sibling,
  local source override, submodule, branch dependency, candidate URL, or
  temporary index.
- Keep the release-ready target `uv.lock` current and registry-resolved. Normal
  sync and release paths must use it in locked mode.
- Treat `packages/gpt2giga-harness/pyproject.toml` as the source of truth for
  version, dependencies, entry points, and the supported Python range.
- Use absolute imports, Ruff formatting, and concise Google-style docstrings.
- Treat OpenAI-, Anthropic-, Gemini-, and GigaChat-shaped behavior as public
  compatibility contracts. A response shape, SSE event, route alias, default,
  or accepted parameter change requires focused compatibility tests and docs.
- Never commit credentials, tokens, real `.env` values, local certificates,
  raw captured traffic, or secret-bearing fixtures.
- Preserve redaction at storage, observability, diagnostics, admin-preview, and
  Harness UI boundaries. Do not apply blanket redaction to public compatibility
  responses. Content capture remains opt-in.

## Unscoped surfaces

- Documentation changes that affect the site must pass the Docusaurus build.
  Keep README/sidebar/locales aligned; links outside `docs/` must work from the
  published site.
- Deployment changes must keep `deploy/`, `Dockerfile*`, `traefik/`, safe
  env examples, user docs, image contents, and health checks aligned.

## Local and ignored state

- `local/` can contain secrets, wheels, media, notebooks, and experiments.
  Do not inspect or edit it unless the user explicitly puts it in scope.
- `docs/internal/` and `scripts/internal/` are ignored by `.gitignore`.
  `docs/codex/` may be locally excluded. These paths can be invisible to
  normal Git status; use `find` and `git check-ignore -v` when the user names
  them.
- Treat `docs/internal/**` and `docs/codex/**` as local coordination state.
  Never force-add them unless the user explicitly asks to publish those files.
- Harness runtime state under `~/.gpt2giga/harness` and project `.giga/`
  belongs to the user. Tests must use temporary directories and must not mutate
  real native Codex, Claude, or Gemini homes.

When continuing a named local roadmap:

1. Read that exact roadmap and its progress file.
2. Resume the next unfinished vertical slice; do not redesign completed work.
3. Implement and verify one slice.
4. Make its dedicated conventional commit when the roadmap requires commits.
5. Record the exact commit hash in the ignored progress file after the commit,
   without staging the roadmap or progress file.

## Commands and validation

Produce frontend assets and install standalone development dependencies:

```bash
npm --prefix packages/gpt2giga-harness/frontend ci --ignore-scripts
npm --prefix packages/gpt2giga-harness/frontend run build
./scripts/ci-base.sh sync
./scripts/ci-base.sh sync-all-extras
./scripts/ci-public-gateway.sh
```

The frontend producer must run before the first clean-checkout `uv sync`;
subsequent sync/build commands consume and verify its ignored asset tree without
running Node.

Repository quality gate:

```bash
./scripts/ci-base.sh ruff-check
./scripts/ci-base.sh ruff-format-check
./scripts/ci-base.sh pytest tests/ --cov=. --cov-report=term --cov-fail-under=80
```

Standalone package build:

```bash
uv build --package gigaloom --no-sources
```

Documentation build:

```bash
npm --prefix docs-site run build
```

Use focused pytest node IDs during iteration. Local pytest defaults to `-n auto`
for directory, multi-file, and full-suite runs; GitHub Actions explicitly pins
`-n 4`. Pass `-n 0` for a focused single-node run when worker startup would cost
more than the test. Run the full quality gate for
cross-package changes, broad refactors, public compatibility changes, release
work, or whenever the user asks for full verification. Run both package builds
after metadata, dependency, entry-point, package-data, Docker, or release
changes. Do not run `tests/live/` or the examples E2E smoke against real
services unless explicitly requested and safely configured.

## Git and completion

- Use Conventional Commit prefixes such as `feat:`, `fix:`, `docs:`,
  `refactor:`, `test:`, and `ci:`.
- Commit only when the user asks or an active roadmap explicitly requires it.
- Stage only task-related tracked files. Recheck `git diff --cached` before
  committing and `git status --short` afterward.
- Report the exact checks run, any skipped environment-dependent checks, and the
  final commit hash.
