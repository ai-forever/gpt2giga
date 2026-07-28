# GigaLoom

[![Quality](https://img.shields.io/github/actions/workflow/status/krakenalt/gigaloom/quality.yaml?branch=main&style=flat-square&label=quality)](https://github.com/krakenalt/gigaloom/actions/workflows/quality.yaml)
[![Documentation](https://img.shields.io/badge/docs-GitHub%20Pages-111827?style=flat-square)](https://krakenalt.github.io/gigaloom/)
[![PyPI](https://img.shields.io/pypi/v/gpt2giga-harness?style=flat-square&label=preview)](https://pypi.org/project/gpt2giga-harness/)
[![License](https://img.shields.io/github/license/krakenalt/gigaloom?style=flat-square)](LICENSE)
[![GigaLoom coverage baseline](./badges/gigaloom-coverage.svg)](./docs/operations.md#quality-baseline)

GigaLoom is a local, provider-neutral control plane for coding agents. It
combines the `giga` CLI, a terminal UI, and a browser cockpit for governed
sessions, approvals, worktrees, schedules, evaluations, and multi-agent
workflows.

The project is an alpha preview. It keeps user state local, redacts sensitive
values at storage and UI boundaries, and fails closed when an action needs
authority that has not been granted.

## Install

Python 3.10–3.14 and an installed provider CLI are required:

```sh
uv tool install --prerelease allow 'gpt2giga-harness==0.5.1a1'
giga doctor
giga --version
```

Start the browser cockpit:

```sh
giga ui
```

Then open `http://127.0.0.1:8091/`. Prefix native provider commands without
changing their remaining arguments:

```sh
giga codex exec --json "review this repository"
giga claude -p "review this repository"
giga gemini -p "review this repository"
```

See [Installation](./docs/installation.md) and
[Quickstart](./docs/quickstart.md) for the complete first-run flow.

## Documentation

| Topic | Guide |
|---|---|
| Product overview | [Documentation home](./docs/index.md) |
| Installation and first run | [Installation](./docs/installation.md) · [Quickstart](./docs/quickstart.md) |
| Architecture and safety boundaries | [Architecture](./docs/architecture.md) · [Security](./docs/security.md) |
| Runtime, backup, and troubleshooting | [Operations](./docs/operations.md) |
| Optional gpt2giga gateway | [Gateway integration](./docs/gateway-integration.md) |
| Development and release | [Contributing](./docs/contributing.md) · [Release](./docs/release.md) |
| Repository migration | [Source history](./docs/source-history.md) |

The published English and Russian documentation is at
<https://krakenalt.github.io/gigaloom/>.

## Gateway integration

The base `gpt2giga-harness` distribution is independently installable and does
not require a gateway source checkout. Direct Chat and the legacy local-gateway
preset are optional:

```sh
uv tool install --prerelease allow 'gpt2giga-harness[gpt2giga]==0.5.1a1'
```

The optional extra consumes the released `gpt2giga` distribution. Its
normalized protocol and compatibility contracts remain owned by the
[gpt2giga gateway project](https://github.com/ai-forever/gpt2giga); see the
[integration guide](./docs/gateway-integration.md) for canonical links.

## Development

```sh
npm --prefix packages/gpt2giga-harness/frontend ci --ignore-scripts
npm --prefix packages/gpt2giga-harness/frontend run build
./scripts/ci-base.sh sync
./scripts/ci-base.sh ruff-check
./scripts/ci-base.sh pytest tests/harness -q
```

Build the standalone distribution with:

```sh
uv build --package gpt2giga-harness --no-sources
```

Read [CONTRIBUTING.md](./CONTRIBUTING.md) before submitting changes and
[GOVERNANCE.md](./GOVERNANCE.md) for ownership and recovery rules. Report bugs
through [GitHub Issues](https://github.com/krakenalt/gigaloom/issues), but send
suspected vulnerabilities through the private channel in
[SECURITY.md](./SECURITY.md).

## Source history

GigaLoom was extracted from the combined `ai-forever/gpt2giga` repository.
Links to that repository in older changelog entries and migration notes are
historical source references, not current development locations. Current
development, issues, documentation, and releases belong to
`krakenalt/gigaloom`.

Licensed under the [MIT License](LICENSE).
