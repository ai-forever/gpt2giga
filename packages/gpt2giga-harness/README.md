# gpt2giga-harness

Local agentic control plane for the `gpt2giga` compatibility gateway. The
distribution provides the `giga` and `gpt2giga-harness` commands, the
`gpt2giga_harness` Python namespace, a durable local worker, and the packaged
Project Cockpit web UI.

> **Alpha status:** `0.0.x` storage, API, adapter, and automation contracts may
> change between releases. Use supervised local workflows first. The package
> metadata in the current checkout is the source of truth for the exact gateway
> dependency.

## Install the current preview

Until the standalone Harness release is available in your package index, run
it from a source checkout:

```sh
git clone https://github.com/ai-forever/gpt2giga.git
cd gpt2giga
git switch feature/harness_enrichment
uv sync --all-packages --all-extras --dev
source .venv/bin/activate
giga doctor
giga ui
```

Keep that environment active when you `cd` to the project you want to manage.
On Windows PowerShell, activate `.venv\Scripts\Activate.ps1` instead.

After publication, the installation will be:

```sh
uv tool install --prerelease allow gpt2giga-harness
giga doctor
giga ui
```

The current `gpt2giga-harness==0.0.1a2` metadata depends exactly on
`gpt2giga==0.2.3a2`. Installing only `gpt2giga` never adds Harness commands or
the `gpt2giga_harness` namespace.

## First local run

From a disposable project directory:

```sh
giga init
giga doctor .
giga doctor . --json
giga ui
```

The doctor reports `ready`, `degraded`, and `blocked` checks for the local
proxy and routes, configured models, adapter CLI versions, workspace and Git,
the durable worker, Harness-managed homes, and managed MCP snapshots. JSON
evidence is redacted and omits absolute workspace paths; every degraded or
blocked first-run prerequisite includes a safe remediation command. Runtime
worker state is inspected read-only.

For a credential-free tour, copy the
[first-run demo](../../examples/harness/first-run-demo/README.md). It keeps
runtime state inside the disposable copy and verifies `giga init`, the local
Echo read path, and the generated smoke eval without starting a proxy or an
external agent CLI.

For the first model-backed north-star flow, copy the
[issue-to-reviewed-patch example](../../examples/harness/issue-to-reviewed-patch/README.md).
It packages reviewed agent profiles, a durable isolated-worktree workflow, and
a post-apply eval while keeping apply, commit, push, and hosted writes explicit.

For unattended compatibility evidence, copy the
[nightly compatibility guardian](../../examples/harness/nightly-compatibility-guardian/README.md).
It packages a pinned Codex/Claude/Gemini eval, exact baseline dimensions, a
read-only triage workflow, and a durable schedule that runs without the UI and
raises Attention only after a tested contract regresses.

Open `http://127.0.0.1:8091/`. `giga ui` starts a durable local worker when
needed; pass `--no-start-worker` when another supervisor owns that lifecycle.
The default loopback binding is intentional. Remote binding requires explicit
authentication and remote-access opt-in.

Useful orientation commands:

```sh
giga config path
giga project info
giga harness list
giga harness inspect codex-cli --json
giga session list
giga native list
giga worker status
```

## Built-in adapters

- Direct Chat through the local gateway;
- Codex CLI;
- Claude Code;
- Gemini CLI;
- Echo for deterministic smoke tests.

External CLIs are discovered on `PATH`. Non-standard absolute paths belong in
the user-owned `~/.gpt2giga/harness/config.toml`:

```toml
[executables]
"codex-cli" = "/custom/bin/codex"
"claude-code" = "/custom/bin/claude"
"gemini-cli" = "C:\\Users\\me\\bin\\gemini.cmd"
```

Manage these values without editing TOML directly:

```sh
giga config set executables.codex-cli /custom/bin/codex
giga config unset executables.codex-cli
giga harness inspect codex-cli --json
```

Configured paths take precedence over `PATH`, must be absolute, and are checked
for executable capabilities before a native or headless run starts.

## Storage and safety boundaries

- User-level coordination state: `~/.gpt2giga/harness/`;
- project configuration and references: `<project>/.giga/`;
- vendor-owned Codex, Claude, and Gemini homes: read or imported only through
  adapter-specific contracts; Harness must not rewrite them;
- edit runs: isolated worktrees with lease and policy checks;
- risky native spawn, remote access, apply, and secret operations: explicit
  approvals.

The control plane stores redacted metadata by default. Content capture and
secret materialization are opt-in and should have explicit access, retention,
and cleanup policies.

## Plugin contract

Third-party adapters register through the `gpt2giga.harnesses` entry-point
group, while import targets live outside the gateway namespace:

```toml
[project.entry-points."gpt2giga.harnesses"]
my-harness = "my_package.my_harness:MyHarness"
```

Use `giga harness scaffold`, `giga harness validate`, and
`giga harness inspect` to develop and diagnose an adapter.

## Upgrade from the combined prerelease

Uninstall both old distributions before installing the split packages. Do not
delete `~/.gpt2giga/harness/` or project `.giga/` state during the package
migration:

```sh
uv tool uninstall gpt2giga
uv tool uninstall gpt2giga-harness
uv tool install --prerelease allow gpt2giga-harness
giga doctor
```

## Documentation

- [Unified Harness guide](https://ai-forever.github.io/gpt2giga/harness)
- [Harness architecture](https://ai-forever.github.io/gpt2giga/architecture/harness)
- [Configuration and security](https://ai-forever.github.io/gpt2giga/harness#configuration)
- [Native sessions](https://ai-forever.github.io/gpt2giga/harness#native-session-mode)
- [Troubleshooting](https://ai-forever.github.io/gpt2giga/harness#troubleshooting)
- [Changelog (RU)](https://github.com/ai-forever/gpt2giga/blob/main/packages/gpt2giga-harness/CHANGELOG.md)
- [Changelog (EN)](https://github.com/ai-forever/gpt2giga/blob/main/packages/gpt2giga-harness/CHANGELOG_en.md)

## Package verification

From the repository root:

```sh
uv sync --all-packages --all-extras --dev
uv run pytest tests/harness -n 4 -q
uv build --package gpt2giga-harness --no-sources
```
