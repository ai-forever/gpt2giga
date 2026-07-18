# gpt2giga-harness

Local agentic control plane for the `gpt2giga` compatibility gateway. The
distribution provides the `giga` and `gpt2giga-harness` commands, the
`gpt2giga_harness` Python namespace, a durable local worker, and the packaged
Project Cockpit web UI.

> **Beta preview:** the `0.1.x` storage, API, adapter, and automation contracts
> are stabilizing but may still change between prereleases. Use supervised local
> workflows first. The package metadata in the current checkout is the source of
> truth for the supported gateway requirement.

## Install the current preview

Until the standalone Harness release is available in your package index, run
it from a source checkout:

```sh
git clone https://github.com/ai-forever/gpt2giga.git
cd gpt2giga
git switch feature/productize_harness
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

The upcoming `gpt2giga-harness==0.1.0b1` metadata requires
`gpt2giga==0.2.4a1`. Installing only `gpt2giga` never adds Harness commands or
the `gpt2giga_harness` namespace.

The base Harness install is intentionally limited to ten reviewed direct
runtime distributions, including the compatible gateway dependency. A clean
installed-artifact audit fails if the resolved environment grows beyond 64
distributions or pulls in Office document libraries, remote-channel SDKs,
external client frameworks, or sandbox-provider SDKs. Those capabilities must
arrive as separately installed providers or Harness plugins; they are not
silently enabled by the base package. Release CI runs the same audit on clean
Python 3.10 and 3.14 environments:

```sh
python -I -m gpt2giga_harness.base_install --json
```

Run that command in a clean base-install environment. An environment where you
deliberately installed an optional provider is expected to report it as
`present` and fail the base-only policy check. The source-checkout development
sync above includes repository development extras and is therefore not a base
footprint measurement.

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
worker state is inspected read-only. The report also includes exact package,
Python, and platform metadata. Use `--fail-on blocked` (or the stricter
`--fail-on degraded`) for CI exit code 1, and `--output harness-doctor.json` to
atomically write a canonical mode-0600 issue attachment while keeping stdout
available.

Every CLI/UI run preflight also projects those checks onto the selected
execution plan before process spawn. Its redacted `readiness` section covers
only the chosen harness, invocation mode, API route/model, workspace policy,
and synchronous or durable delivery path. Missing required capabilities block;
degraded capabilities include the same bounded remediation commands as doctor.
Unrelated proxy, external-CLI, or worker failures do not block the independent
local Echo path.

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

For parallel evidence-backed review, copy the
[cross-harness review team](../../examples/harness/cross-harness-review-team/README.md).
It fans out read-only explorer, security, tests, and maintainability roles
across Codex, Claude, and Gemini, then synthesizes retained child artifacts
without introducing a shared writable workspace.

Open `http://127.0.0.1:8091/`. `giga ui` starts a durable local worker when
needed; pass `--no-start-worker` when another supervisor owns that lifecycle.
The default loopback binding is intentional. Remote binding requires explicit
authentication and remote-access opt-in.

The root URL opens Cockpit V2. During its release-level rollback window, the
previous no-build cockpit remains available at `http://127.0.0.1:8091/legacy`
without migrating or rewriting Harness runtime state.

After the first run starts, Workbench reveals a compact Run → Evidence → Review
→ Reuse path. Once the run reaches a terminal state, the exact retained trace
is available in Runs; prompts, responses, and workspace paths are not copied
into the transition summary. For a retained isolated patch, the Review tab
opens that run's diff while apply and approval remain separate explicit
operator actions. An eligible successful run exposes its existing provenance
and promotion state under Reuse. Promotion preview/apply and later scheduling
remain separate explicit actions.

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

External CLI execution is supported only when both the bounded help probe and
the declared version window pass: Codex CLI `>=0.144.0,<0.145.0`, Claude Code
`>=2.1.0,<2.2.0`, and Gemini CLI `>=0.46.0,<0.47.0`. Inspect
`compatibility.version_contract` with `giga harness inspect <id> --json`.
Older or capability-incomplete binaries are `unsupported`; newer or
unparseable versions are `degraded` and remain fail-closed until their fixtures
and support window are reviewed.

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

Third-party adapters register through the versioned, provider-neutral
`agent_workbench.harness_adapters.v1` entry-point group, while import targets
live outside the gateway namespace:

```toml
[project.entry-points."agent_workbench.harness_adapters.v1"]
my-harness = "my_package.my_harness:MyHarness"
```

The legacy `gpt2giga.harnesses` group remains a compatibility alias. Packages
may advertise the same target through both groups during migration; equivalent
duplicates are loaded once, while conflicting adapter IDs fail without
overwriting the first registration.

Use `giga harness scaffold`, `giga harness validate`, and
`giga harness inspect` to develop and diagnose an adapter. Pass
`--output <directory>` to scaffold a complete out-of-tree package with a
versioned, content-free manifest, neutral entry points, a fake provider fixture,
and a hermetic conformance test. After installing the package, run
`giga harness conformance <adapter-id> --json`.

SDK API v1 reports execution, sessions, approvals, attachments, integrations,
recovery, history, telemetry, and packaging separately. A capability passes
only when the manifest declares it and a corresponding behavioral probe passes;
omitted claims remain `unsupported` and are never inferred from legacy adapter
metadata.

## Back up user state

Stop the Cockpit, durable workers, and active runs before taking an offline
backup. Write the archive outside `~/.gpt2giga/harness` and verify it before an
upgrade or package rollback:

```sh
giga state backup --output ../gpt2giga-harness-state.zip
giga state verify ../gpt2giga-harness-state.zip --json
# after stopping Harness, restore into an absent directory or confirm replacement
giga state restore ../gpt2giga-harness-state.zip --replace --json
```

The versioned archive preserves Harness-owned files and consistent SQLite
snapshots with deterministic hashes. It excludes transient lock, WAL, SHM, and
temporary files, rejects symbolic links, and fails if source state changes
during capture. The archive is created with mode `0600`, but it may still
contain opt-in captured content, attachments, or managed configuration; treat
it as private state, not as a support bundle. Project-local `.giga/` directories
remain separate and should stay in the project backup or version-control plan.

`giga state restore` verifies the archive again, rejects a runtime schema newer
than the installed Harness supports, stages every file with its retained mode
and SQLite integrity check, then publishes the directory through an offline
sibling swap. An existing destination is never overwritten without
`--replace`, and active lock/WAL/SHM markers or a concurrent state change fail
before publication. Older runtime schemas are migrated only by the next normal
Harness startup; there is no reverse migration. For rollback, restore the
pre-upgrade archive after reinstalling the package version that created it.

`giga runtime export` remains the redaction-safe coordination export for issue
reports.

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
uv run pytest tests/harness -q
uv build --package gpt2giga-harness --no-sources
```
