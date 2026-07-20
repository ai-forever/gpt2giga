# gpt2giga-harness

Local agentic control plane for the `gpt2giga` compatibility gateway. The
distribution provides the `giga` and `gpt2giga-harness` commands, the
`gpt2giga_harness` Python namespace, a durable local worker, and the packaged
Project Cockpit web UI.

> **Alpha preview:** the `0.3.x` storage, API, adapter, and automation contracts
> are stabilizing but may still change between prereleases. Use supervised local
> workflows first. The package metadata in the current checkout is the source of
> truth for the supported gateway requirement.

## Install the current preview

Install the published prerelease from your package index:

```sh
uv tool install --prerelease allow gpt2giga-harness
giga doctor
giga --version
giga
giga ui
```

For Direct Chat and the `gpt2giga` provider preset, install the explicit extra:

```sh
uv tool install --prerelease allow 'gpt2giga-harness[gpt2giga]'
```

The standard install includes the terminal workbench. Start it from the project
you want to manage:

```sh
giga
```

The default TUI mode composes the existing Harness application in-process: it
does not open a browser or start FastAPI/uvicorn. It provides keyboard-first
project and session navigation, session creation/resume, and an explicit
provider/Harness/model/transport readiness panel. Use `giga --attach
http://127.0.0.1:8091` only when an existing Harness UI/worker already owns the
runtime. Attach mode uses the same cookie/bootstrap-authenticated REST contracts
as Cockpit and never falls back silently to in-process mode. English and Russian
presentation catalogs are available through `--locale en|ru`.

Bare `giga` is the canonical TUI entry point; `giga tui` remains a compatibility
alias but is not a separate product surface. Root `--help`, `--version`, and TUI
options are owned by the same low-overhead TUI entry point without importing
Textual for metadata-only requests. On a supported interactive terminal, `chat`,
`run --agent`, and `session list|show|create|turn` deep-link into that same TUI
with their workspace, session, Harness, model, mode, transport, and prompt intent
preserved. There is no parallel transcript renderer.

| Command shape | Owner |
| --- | --- |
| bare `giga`, `giga tui`, human `chat`, `run --agent`, and selected `session` actions | built-in TUI |
| `--non-interactive`, `--json`, `--dry-run`, redirects, pipes, CI, admin commands, and session event/approval inspection | non-interactive CLI |
| `giga open ...` | explicit external handoff |

Machine routes never initialize Textual, prompt, or emit terminal control
sequences. `TERM=dumb` and unsupported terminals fail closed for an explicitly
requested TUI; redirected human commands retain their established CLI bytes,
schemas, exit codes, and stdout/stderr behavior.

If you installed the earlier optional-TUI prerelease, upgrade the existing tool;
do not keep or add a `[tui]` extra:

```sh
uv tool upgrade --prerelease allow gpt2giga-harness
giga --version
giga
```

Rollback uses the exact previously reviewed version, for example `uv tool
install --force 'gpt2giga-harness==<previous-version>'`. Remove the preview with
`uv tool uninstall gpt2giga-harness`; runtime state remains under the user-owned
Harness data directory and is not deleted by package uninstall.

For development or when the prerelease is not yet mirrored by your package
index, run it from a source checkout:

```sh
git clone https://github.com/ai-forever/gpt2giga.git
cd gpt2giga
uv sync --all-packages --all-extras --dev
source .venv/bin/activate
giga doctor
giga ui
```

Keep that environment active when you `cd` to the project you want to manage.
On Windows PowerShell, activate `.venv\Scripts\Activate.ps1` instead.

The current `gpt2giga-harness==0.3.0a1` metadata keeps
`gpt2giga==0.2.4a1` in the `gpt2giga` optional extra. Installing only
`gpt2giga` never adds Harness commands or the `gpt2giga_harness` namespace.

The provider-neutral base Harness install is intentionally limited to nine
reviewed direct runtime distributions. A clean installed-artifact audit fails
if the resolved environment grows beyond 64 distributions or pulls in the
`gpt2giga`/GigaChat provider preset, Office document libraries, remote-channel
SDKs, external client frameworks, or sandbox-provider SDKs. Those capabilities
must arrive through an explicit extra, separately installed provider, or
Harness plugin; they are not silently enabled by the base package. Release CI
runs the audit plus installed terminal-command smoke on clean Python 3.10–3.14
environments across Linux, macOS, and Windows:

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

Retained assistant messages expose a Copy action that fetches the complete
stored response instead of copying a bounded read-model preview. For structured
and one-shot runs, only the latest retained user message exposes a pencil
action. Resubmitting that edit replaces the active turn and its following
assistant response in Workbench, while the superseded run remains retained in
Runs for audit. Native terminal sessions do not expose the pencil because a
retained interactive process cannot be rewound safely.

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

## Provider-neutral routes

Cockpit Settings and `giga provider` manage reference-only profiles for
OpenAI-, Anthropic-, and Gemini-compatible endpoints. A profile owns its
protocol dialect, base URL, route prefix, authentication reference, enabled or
offline state, and model defaults for coding, titles, evaluation, and fallback.
Credential values are never accepted by the settings API or returned to the
browser; they are resolved only at the owning request/subprocess boundary.

```sh
giga provider list --json
giga provider add openai-production \
  --name "OpenAI production" \
  --protocol openai_compatible \
  --dialect openai-responses-v1 \
  --base-url https://api.openai.com \
  --route-prefix /v1 \
  --authentication secret_reference \
  --secret-reference-kind environment \
  --secret-reference-name OPENAI_API_KEY \
  --coding-model <model-id> \
  --json
giga provider show openai-production --json
```

Use `giga provider test` or `discover` for an explicit bounded check; failures
remain content-free and never trigger a silent provider fallback. Migrate old
proxy/API-mode/model defaults only after previewing the forward-only plan and
choosing a pre-upgrade backup outside the Harness data directory:

```sh
giga provider migrate-legacy --dry-run --json
giga provider migrate-legacy \
  --backup /safe/path/harness-before-provider-migration.zip \
  --json
```

Rollback means stopping Harness and restoring that verified archive; reverse
migration is intentionally unsupported.

## Built-in adapters

- Direct Chat through the local gateway;
- Codex CLI through durable `native_structured` app-server sessions, a managed
  native terminal, or an explicit one-shot compatibility run;
- Gemini CLI through durable `native_structured` ACP sessions, a managed native
  terminal, or an explicit one-shot compatibility run;
- Claude Code through an explicit one-shot run or managed native terminal,
  plus a separate provider-owned Remote Control/Desktop handoff preview;
- Echo for deterministic smoke tests.

Workbench and `giga session turn` use the canonical transport names
`native_structured`, `native_terminal`, and `one_shot`. Codex and compatible
Gemini installations default to structured durable sessions. Claude embedded
structured execution remains unavailable; its provider handoff is explicitly
non-durable and does not become a Harness-owned session. Inspect the exact
capability and blocker before execution:

```sh
giga harness inspect gemini-cli --json
giga session turn <session-id> --transport native_structured --prompt "Inspect"
```

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
for executable capabilities before a structured, terminal, or one-shot run
starts.

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

### Read-only skills.sh metadata proxy

`giga-skills-catalog-proxy` is an independently deployable, metadata-only
boundary for the authenticated `https://skills.sh/api/v1/` catalog. It exposes
only bounded GET list, search, detail, and health routes, strips detail file
contents, never accepts an arbitrary upstream URL, and resolves
`VERCEL_OIDC_TOKEN` inside each upstream request without persisting or logging
the bearer value.

Safe local configuration keeps the listener private by default:

```sh
export VERCEL_OIDC_TOKEN='<request-scoped token supplied by Vercel>'
export GIGA_SKILLS_PROXY_HOST=127.0.0.1
export GIGA_SKILLS_PROXY_PORT=8092
export GIGA_SKILLS_PROXY_RATE_LIMIT=120
giga-skills-catalog-proxy
```

Binding to `0.0.0.0` is explicit and should be done only behind an HTTPS
reverse proxy with its own access controls. The service never installs catalog
entries and does not grant installation authority.

Point Cockpit search at that fixed proxy origin when starting the UI:

```sh
export GIGA_SKILLS_PROXY_ORIGIN=http://127.0.0.1:8092
giga ui
```

### Federated Skills and MCP lifecycle

Cockpit's **Plugins** area and `giga integration list --json` read the same
offline-first inventory. `skills-sh` supplies hosted Skill metadata through the
proxy above; `neuraldeep` supplies public Skill and MCP metadata. Source health,
popularity, curation, and presence never authorize installation. The catalog
keeps its last good state on source failure, and a NeuralDeep MCP card can only
correlate with an exact official MCP Registry identity without replacing the
official immutable version or integrity.

The **Skills**, **Plugins**, and **MCP** pages expose **Add Skill**, **Add
Plugin**, and **Add MCP** respectively. Git Skill import accepts public GitHub
repository and `/tree/<ref>` URLs, pins the resolved commit, lets the operator
choose one bounded `SKILL.md`, and shows its instructions before approval.
Native Plugin/Extension import requires a reviewed `integration-package.json`;
raw MCP import accepts an exact stdio or HTTP descriptor. Shared root Skills
from `~/.agents/skills` and provider-specific Skill homes appear in inventory
and can be filtered by Codex, Claude, Gemini, or Harness. Override shared roots
with the OS-path-separated `GIGA_ROOT_SKILLS_DIRS` variable.

An external Skill must match its reviewed immutable reference and content hash
before bounded `SKILL.md` validation and target projection. A normalized MCP
candidate likewise keeps exact package integrity, argv, origins, secret
references, permissions, and native-consent boundaries in the preview. Review
and operate one target with:

```sh
giga integration preview --source catalog --catalog-id <id> \
  --target <target-id> --scope managed_home --json
giga integration apply <flow-id> --plan-id <plan-id> \
  --authority <operator> --json
giga integration status <flow-id> --json
giga integration rollback <flow-id> --json
```

For **Install to all Harnesses**, use `group-preview`, `group-apply`,
`group-status`, `group-recover`, and `group-rollback`. Skills expand to Codex,
Claude, and Gemini; MCP expands to those managed native homes plus the
Harness-managed MCP inventory. Every child preview must pass before mutation.
Cross-root apply is a durable compensating transaction: partial failure rolls
back owned verified children or records exact recovery actions. Updates require
a new immutable pin, preview, and approval. Federated discovery never implies
Plugin installation or network authority; Plugin execution requires an exact
reviewed manifest, and real user homes are never the default mutation scope.

The equivalent API begins at `GET /api/integrations`, with single-target flows
under `/api/integrations/flows` and grouped flows under
`/api/integrations/groups`.

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
