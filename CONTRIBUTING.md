# Contributing to GigaLoom

Thank you for helping improve GigaLoom.

## Before opening work

- Use GitHub Issues for bugs and proposals that are safe to discuss publicly.
- Report suspected vulnerabilities privately according to
  [SECURITY.md](SECURITY.md).
- Never include credentials, tokens, private user content, native-home data,
  raw provider traffic, or secret-bearing fixtures.
- Historical source issues may be linked as context, but their authorship,
  comments, reviews, and timestamps must not be presented as transferred.

## Development

Produce the frontend before the first clean environment sync:

```bash
npm --prefix packages/gpt2giga-harness/frontend ci --ignore-scripts
npm --prefix packages/gpt2giga-harness/frontend run build
./scripts/ci-base.sh sync
```

Run focused tests for the changed owner first. For a broad change, use:

```bash
./scripts/ci-base.sh ruff-check .
./scripts/ci-base.sh ruff-format-check .
./scripts/ci-base.sh pytest tests/ --cov=. --cov-report=term --cov-fail-under=80
npm --prefix docs-site run build
```

Do not run live provider tests or access real native CLI homes unless a task
explicitly authorizes and safely configures them.

## Pull requests

- Keep one coherent change per pull request and use Conventional Commit
  messages.
- Explain behavior and compatibility impact, list exact verification, and
  update English and Russian documentation together.
- Add focused compatibility tests for public response shapes, SSE events,
  route aliases, defaults, or accepted parameters.
- Do not add an editable gateway sibling, source override, submodule, branch
  dependency, or a persisted root `uv.lock`.
- Dependency, release, security-boundary, and governance changes require an
  owner review under [GOVERNANCE.md](GOVERNANCE.md).

By contributing, you agree that your contribution is provided under the
repository's [MIT license](LICENSE).
