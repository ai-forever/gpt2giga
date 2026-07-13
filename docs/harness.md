# Unified Harness

:::warning[Alpha preview — under active development]

The `gpt2giga-harness` 0.0.x line is an early preview for testing and feedback.
The UI, CLI, project YAML, runtime schema, and upgrade behavior can change while
the product is being developed. Use it for local evaluation and supervised
workflows, not as a production-critical or unattended multi-user service.

:::

Unified Harness is a local project cockpit on top of `gpt2giga`. It gives you
one place to run a task through direct GigaChat, Codex CLI, Claude Code, Gemini
CLI, or a plugin harness; compare the results; inspect what happened; and decide
which changes are allowed back into your project.

The Harness is not another model and it does not replace the compatibility
gateway or the agent CLIs. It coordinates them and keeps a normalized local
record of runs, approvals, artifacts, and reusable project automation.

## Why use it

Working with several agent CLIs usually means different commands, histories,
permission models, and output formats. Unified Harness adds a common layer for:

- **one project cockpit** — start from the current repository with `giga ui`;
- **repeatable runs** — save agents, prompts, evals, workflows, and schedules
  under `.giga/` instead of rebuilding the setup for every task;
- **comparison** — send the same task to several available harnesses in Arena
  and inspect the results side by side;
- **review before mutation** — keep edit runs in isolated Git worktrees and put
  apply/branch actions behind explicit approvals;
- **traceability** — inspect durable run status, attempts, redacted events,
  artifacts, diffs, and provenance after the browser or UI server restarts;
- **local control** — keep project configuration and runtime history on your
  machine rather than introducing a hosted control plane.

### Mental model

| Layer | Responsibility |
| --- | --- |
| `gpt2giga` gateway | Exposes OpenAI-, Anthropic-, and Gemini-shaped HTTP APIs backed by GigaChat. |
| Unified Harness | Selects a harness and model, coordinates runs, stores local history, and exposes the CLI/UI. |
| Direct Chat or agent CLI | Performs the actual model or agent work. External CLIs remain responsible for behavior inside their own process. |

This separation matters: an approval shown by Unified Harness covers actions it
owns, such as spawning a run or applying a captured patch. It cannot claim to
observe every internal action performed by a black-box external CLI.

## Is the alpha preview for you?

Try it now if you want to evaluate a local agent cockpit, compare harnesses,
prototype reviewable workflows, or give feedback while the interfaces are
still being shaped. Start with `echo`, dry-runs, `plan`/`read` modes, and a test
repository before allowing edits.

Wait for a later release if you need a stable automation API, guaranteed
backward compatibility, high availability, central multi-user administration,
or a security boundary around arbitrary behavior inside third-party CLIs.

During the alpha:

- read release notes before upgrading and back up `~/.gpt2giga/harness` plus
  important project `.giga/` definitions;
- expect optional features to depend on the exact Codex, Claude, or Gemini CLI
  installed on the workstation;
- keep the UI on its default loopback address unless you deliberately configure
  remote authentication and TLS;
- review generated `.giga/` files before committing them, and never put secrets
  in project configuration;
- report bugs with `giga doctor`, the Harness version, reproduction steps, and
  redacted diagnostics in [GitHub Issues](https://github.com/ai-forever/gpt2giga/issues).

## Quickstart

### 1. Get the preview and check the workstation

The source checkout is the current, always-available alpha path:

```bash
git clone --branch feature/unified_harness \
  https://github.com/ai-forever/gpt2giga.git
cd gpt2giga
uv sync --all-packages --all-extras --dev
source .venv/bin/activate
giga doctor
giga harness list
```

Keep the checkout virtual environment activated in every terminal used for the
preview. You can then `cd` to the project you want to inspect while `giga` and
`gpt2giga` continue to resolve from the checkout. On Windows, activate
`.venv\Scripts\Activate.ps1` instead.

After the standalone preview appears in your package index, the shorter install
path is:

```bash
uv tool install gpt2giga-harness
giga doctor
```

The distribution installs the exact compatible gateway dependency declared in
its package metadata and provides the `giga` and `gpt2giga-harness` commands.

Requirements are Python 3.10–3.14 and `uv`. Direct GigaChat runs also need the
gateway credentials described in the [gpt2giga quickstart](quickstart.md).
Codex, Claude Code, and Gemini integrations require the matching external CLI
executable on `PATH` (or an explicit executable override) plus a configured
local gateway. They do not require a separate vendor login for the documented
Harness route. Unavailable CLIs stay disabled rather than breaking the cockpit.

### 2. Initialize a disposable or test project

Run the first tour in a repository where generated project files and test edits
are safe to inspect:

```bash
cd /path/to/project
giga doctor
giga init
```

`giga init` creates non-secret starter configuration, agent profiles, prompts,
an eval, and a review workflow under `.giga/`. Existing files are not replaced
unless you pass `--overwrite`.

Before connecting a real model, verify the local execution path with the
credential-free `echo` harness:

```bash
giga harness run echo \
  --workspace . \
  --prompt "Summarize the selected task"
```

Preview an external agent command without launching it:

```bash
giga run \
  --agent codex \
  --mode read \
  --workspace . \
  --dry-run \
  "Summarize this repository"
```

### 3. Connect GigaChat

For browser and durable-worker runs, keep the gateway running in a separate
terminal. Activate the same source-checkout environment in that terminal, then
run:

```bash
source /path/to/gpt2giga/.venv/bin/activate
gpt2giga
```

With tool installations, install/expose the gateway command separately as
described in the [gpt2giga quickstart](quickstart.md), then run `gpt2giga`.

In another terminal, inspect the harness environment:

```bash
giga doctor
giga harness list
```

If the proxy is not running, `giga chat`, `giga harness run direct-chat`, and
real external agent CLI runs try to start a local sidecar by default. Disable
that for a single command with:

```bash
giga chat --no-start-proxy --api-mode v2 --model GigaChat-2-Max "Привет"
```

Run direct Chat Completions smoke tests through explicit backend routes:

```bash
giga chat --api-mode v2 --model GigaChat-2-Max "Привет"
giga chat --api-mode v1 --model GigaChat-2-Max "Привет"
```

The same flow through the generic harness command:

```bash
giga harness run direct-chat \
  --api-mode v2 \
  --model GigaChat-2-Max \
  --prompt "Hello from the harness"
```

### 4. Open the project cockpit

Open the local UI:

```bash
giga ui
```

Then open `http://127.0.0.1:8091/`. A useful first tour is:

1. Confirm the current repository and branch in **Work**.
2. Select `echo` and submit a harmless prompt.
3. Open **Runs** and inspect the attempt, trace, and stored redacted payloads.
4. Use **Arena** to compare two available harnesses with the same task.
5. Inspect **Approvals**, **Agents**, **Workflows**, **Evaluate**, **Tools**, and
   **Scheduled** before enabling edits or unattended execution.

`giga ui` starts a local durable worker automatically when no online worker is
registered. Use `giga ui --no-start-worker` when a separately supervised worker
already exists or when the UI should only inspect durable state.

The standalone worker owns headless UI runs, leases, heartbeats, timeouts,
retries, and cancellation, so a run survives a browser or UI-server restart.
Arena children and Eval case/harness pairs use the same independent durable
jobs and update their transparent parent JSON records as attempts finish.
Use `giga worker status` to inspect registered workers, or run a temporary
worker with `giga worker stop-on-idle --idle-seconds 30`. Workers deliberately
do not auto-start a proxy: start `gpt2giga` yourself and configure
`GPT2GIGA_HARNESS_API_KEY` when a harness needs the proxy. This avoids treating
the UI process's temporary sidecar key cache as durable worker state.

The `Runs` area is the durable queue and history view. It filters queued,
running, blocked, approval-needed, failed, canceled, and completed jobs; shows
attempt count, retries, duration, selected metrics, and worker ownership; and
reconnects to active SSE streams after a browser or UI-server restart. Opening
a run loads a bounded hierarchical trace first. Individual redacted event
payloads and artifacts are fetched only when inspected, and model reasoning is
never exposed by the trace API or rendered in the timeline. Safe retry is
available only when the latest failed attempt declares a read-only,
deterministic, or otherwise retry-safe idempotency class.

The lightweight Runs Center API is cursor-paginated:

```text
GET  /api/runs?status=running&limit=25&cursor=...
GET  /api/runs/{run_id}/summary
GET  /api/runs/{run_id}/trace?limit=100&cursor=...
GET  /api/runs/{run_id}/events/{event_id}
POST /api/runs/{run_id}/retry
```

The `Approvals` area is the policy inbox for actions owned by Unified Harness.
The shared taxonomy covers workspace reads/writes, process and network access,
MCP server/tool actions, git apply/branch, external writes, and schedule
operations. Each decision records whether enforcement is owned by the Harness,
delegated to a CLI sandbox, or advisory/unobservable. The UI never claims that
it can inspect arbitrary actions inside black-box Codex, Claude, or Gemini
subprocesses.

Interactive runs use the `interactive` profile by default. Select
`review every action` in Advanced settings to persist a pre-spawn approval and
put the durable job in `waiting_approval` without creating an attempt, process,
or lease. An approval requeues the same logical job; denial cancels it. Apply
and branch actions always require an approval before mutating the source
checkout. Allow-once grants are consumed, run grants stay scoped to one run,
and project grants require an expiry.

```text
GET  /api/policy/profiles
GET  /api/approvals?status=pending
POST /api/approvals/{approval_id}/decision
```

### Scheduled jobs

Project schedules are shareable YAML definitions under
`.giga/schedules/<schedule_id>.yaml`; mutable enablement, next-run state, and
occurrence history stay in `runtime.sqlite3`. A schedule captures an immutable,
redacted content hash and snapshot of its agent, preset, workflow, or eval
target. Editing any material field pauses the schedule and invalidates its
previous `Test now` grant.

One-shot, fixed interval, and RRULE cadence are supported with an explicit IANA
timezone. Occurrences are stored as UTC instants. Nonexistent spring-forward
times are recorded as misfires, and ambiguous fall-back times run once at the
first instant. The default overlap and misfire policies both skip rather than
silently catch up or run concurrent copies.

The local worker evaluates due schedules before claiming ordinary jobs, so an
open browser is not required. Enable is blocked until the exact schedule hash
passes backend `Test now` and a live worker is registered. Scheduled edits use
the unattended policy profile and fail closed unless an isolated Git worktree
can be created; `schedule.unattended_edit` remains approval-gated. Resume mode
serializes work per session and stores its explicit history cutoff.

```bash
giga schedule preview schedule.yaml --workspace /path/to/project --json
giga schedule create schedule.yaml --workspace /path/to/project --json
giga schedule list --workspace /path/to/project --json
giga schedule test-now daily-review --workspace /path/to/project --json
giga schedule enable daily-review --workspace /path/to/project --json
giga schedule run-now daily-review --workspace /path/to/project --json
giga schedule pause daily-review --workspace /path/to/project --json
```

The authenticated API exposes matching CRUD, preview, test, enable/pause,
resume, and run-now operations under `/api/schedules`. Create/update, enable,
and run-now use the shared Approval Center policy actions. Deleting a schedule
archives its SQLite audit state instead of erasing occurrence history. The
top-level `Scheduled` area adds list, upcoming-calendar, and immutable-history
views plus a typed wizard for target, cadence, destination, worktree isolation,
concurrency, retry/misfire policy, and notifications. It explains the exact-hash
`Test now` gate and worker-online requirement before enable.

The same area contains the project Attention Inbox. Pending approvals, failed
durable jobs, and schedules in `needs_attention` are derived from their source
audit records rather than copied into a second queue. Marking an item read only
stores acknowledgement state in `runtime.sqlite3`; it never deletes the job,
approval, schedule snapshot, or occurrence history. Desktop notifications are
optional, browser-session-only, and link back to the relevant approval, run, or
schedule. A schedule must opt in to schedule-finding notifications explicitly.

```text
GET  /api/automation?workspace=/path/to/project
GET  /api/attention?workspace=/path/to/project
POST /api/attention/read
```

The top-level `Tools` area is the MCP connection center. It shows redacted
project descriptors, transport and trust state, per-harness compatibility,
latest health, discovered server instructions, tools/resources/prompts, input
and output schemas, risk labels, and bounded probe history. It does not execute
tools or write harness config.

From a project directory, inspect or initialize the project cockpit config:

```bash
giga project info
giga project init
# Short alias:
giga init
```

By default the UI binds to `127.0.0.1:8091`. Local requests receive an opaque
HttpOnly, `SameSite=Strict` browser-session cookie. To bind remotely, configure
a strong bootstrap token in the environment and opt in explicitly:

```bash
export GPT2GIGA_HARNESS_UI_BOOTSTRAP_TOKEN="$(openssl rand -hex 32)"
export GPT2GIGA_HARNESS_UI_ALLOWED_HOSTS=harness.example.internal
giga ui --host 0.0.0.0 --allow-remote
```

Terminate TLS in front of a remote listener: remote cookies are `Secure`, the
bootstrap token is exchanged through `Authorization: Bearer ...`, and it is
never accepted in a URL. Without remote authentication, data APIs return `401`
and mutating APIs fail closed with `403`. Host and same-origin checks apply to
the shell, API, assets, and SSE connections.

Treat the bootstrap token as same-principal operator access, not as a tenant or
read-only credential. An authenticated operator can select any workspace the
Harness OS account can access, preview supported files, and start approved
processes there. Share the token only with operators who may act with that OS
account's filesystem and process privileges.

## Configuration

CLI flags override environment variables. Useful variables:

```bash
GPT2GIGA_HARNESS_PROXY_URL=http://127.0.0.1:8090
GPT2GIGA_HARNESS_API_KEY=<local-proxy-api-key>
GPT2GIGA_HARNESS_DEFAULT_MODEL=GigaChat-2-Max
GPT2GIGA_HARNESS_DEFAULT_API_MODE=v2
GPT2GIGA_HARNESS_UI_HOST=127.0.0.1
GPT2GIGA_HARNESS_UI_PORT=8091
GPT2GIGA_HARNESS_UI_BOOTSTRAP_TOKEN=<strong-random-secret-for-remote-ui>
GPT2GIGA_HARNESS_UI_ALLOWED_HOSTS=harness.example.internal
GPT2GIGA_HARNESS_AUTO_START_PROXY=True
GPT2GIGA_HARNESS_PROXY_START_TIMEOUT_SECONDS=15
GPT2GIGA_HARNESS_TIMEOUT_SECONDS=3600
GPT2GIGA_HARNESS_DATA_DIR=~/.gpt2giga/harness
```

If `GPT2GIGA_HARNESS_API_KEY` is not set, the harness falls back to
`GPT2GIGA_API_KEY` for calls to the local proxy. It never passes
`GIGACHAT_CREDENTIALS`, OAuth tokens, certificates, or `.env` contents to
external agent CLIs.

Auto-start is local-only. It supports `http://127.0.0.1:<port>`,
`http://localhost:<port>`, and `http://[::1]:<port>`. It refuses remote hosts,
does not create fake upstream credentials, and starts the child proxy with a
generated local `GPT2GIGA_API_KEY` if one is not already configured.

External agent harnesses run the same proxy preflight before launching Codex,
Claude Code, or Gemini CLI. If a sidecar is started, the generated local proxy
key is passed only through the agent-specific local API-key environment variable
and remains redacted from JSON/UI results.

### Project Config

`giga project init` creates a non-secret `.giga/harness.toml` in the current
project root. If the command runs inside a git repository, the git top-level
directory is used as the project root; otherwise the current directory is used.

The config stores project defaults such as harness, model, explicit `v1`/`v2`
API mode, mode, enabled harnesses, presets, and future attachment safety
defaults. It must not contain API keys, tokens, cookies, credentials, private
keys, certificates, or `.env` contents.

Project init also creates safe prompt templates under `.giga/prompts/` and a
local smoke eval under `.giga/evals/smoke.yaml`.
Presets can render inline `prompt` text or a relative `prompt_file` inside the
project root. Supported template variables are:

- `{{project_name}}`
- `{{branch}}`
- `{{selected_files}}`
- `{{selected_files_inline}}`
- `{{last_run_diff}}`
- `{{user_prompt}}`

The same variables can also be written as `${project_name}` or `$project_name`.
Preset files are never allowed to point outside the project root.

`giga ui` also keeps mutable, non-secret cockpit state per project under the
harness data directory. This includes the last selected harness, model, API
mode, run mode, invocation mode, and selected session. It is intentionally local
state, not repository config.

Use JSON output when wiring tools or checking what `giga ui` will use:

```bash
giga project info --json
giga project init --name my-project --json
giga preset list --json
giga preset run fix_tests --prompt "focus on tests/harness" --dry-run --json
```

In the browser cockpit, preset chips fill the composer with the rendered prompt
and preset defaults. They do not execute automatically; use `Run` or `Compare`
after reviewing the filled request.

### Reusable Agent Profiles

Project agents are reusable role/configuration profiles over existing harnesses.
They live in `.giga/agents/*.yaml`; `giga init` creates Planner, Explorer,
Implementer, Reviewer, Test Runner, and Release Assistant starters. Profiles can
bind instructions, harness/model/reasoning effort/route, context and memory selectors, MCP tool
descriptor ids, permission/workspace policy, budgets, and an expected artifact.
They never contain literal secrets or paths that escape the project.

```bash
giga agent list --workspace .
giga agent show reviewer --workspace . --json
giga agent validate .giga/agents/reviewer.yaml
giga agent run reviewer --workspace . --prompt "Review this patch" --dry-run
```

The first-class `/agents` Agent Studio lists and validates profiles, previews a
redacted diff, checks the source SHA-256 ETag, and performs an explicit atomic
Apply. Duplicate creates a draft until Apply is selected. The same reusable
project authoring service is intended for later Workflow Builder and Schedule
Wizard surfaces; those features must not write project YAML directly.

`Run as Agent` submits a normal durable manual job. Each run stores an immutable
redacted `agent_profile_snapshot` and `agent_id`, so later YAML edits do not
rewrite history. Live activity remains in Work and Runs rather than being
duplicated in Agent Studio.

Authenticated APIs:

- `GET /api/agents` and `GET /api/agents/{agent_id}`;
- `POST /api/agents/validate`;
- `POST /api/agents/{agent_id}/draft` and `/apply`;
- `POST /api/agents/{agent_id}/duplicate` and `/run`.

### Versioned Workflows

Project workflows are bounded DAG definitions under `.giga/workflows/*.yaml`.
`giga init` installs a read-only `review-team` starter that plans, fans out to
security/test-gap/maintainability reviews, and synthesizes their results. Every
run stores the exact SHA-256 definition hash plus immutable workflow and step
snapshots, so later YAML edits cannot rewrite execution history.

The version 1 IR supports `agent`, `arena`, `eval`, explicit `approval`, safe
built-in `transform`, and `join` steps. Definitions may set dependencies,
`on_success`/`on_failure`/`always` conditions, bounded concurrency and fan-out,
retries, timeouts, typed input maps, output names, and artifact references.
Cycles, unknown dependencies, arbitrary transform code, more than 64 steps, or
fan-out above 16 fail validation. Arbitrary shell nodes are intentionally not
part of the workflow IR.

```bash
giga workflow list --workspace .
giga workflow show review-team --workspace . --json
giga workflow validate .giga/workflows/review-team.yaml
giga workflow run review-team --workspace . --prompt "Review this change" --dry-run
giga workflow run review-team --workspace . --prompt "Review this change" --json
giga workflow status <workflow_run_id> --json
giga workflow cancel <workflow_run_id>
```

Agent, arena, and eval work is submitted through the same durable job worker as
manual Runs. Workflow cancellation persists first and propagates to every
active child job. Explicit approval steps enter `waiting_approval` and reuse the
Approval Center; no process or lease is created for the approval node itself.
Safe transform/join nodes run locally without arbitrary code execution.

The built-in Review Team is the first collaborative workflow rather than an
Arena alias. Planner output is summarized and handed to three parallel
reviewers; their summaries and selected artifact references are then handed to
the Synthesizer. Handoffs are redacted and bounded to 8,000 characters and 16
artifact references per dependency. Each child job retains its immutable agent
profile snapshot, including its harness, model, reasoning effort, tools,
permission profile, and budgets.

Editing agents are always forced into a distinct detached Git worktree,
regardless of a weaker policy in their profile. Worktree preparation fails
closed and never falls back to the source checkout. Completed, failed, and
interrupted worktrees remain available for review until explicitly discarded.
Their visible output is projected into a strict handoff vocabulary: `plan`,
`selected_files`, `patch`, `diff`, `test_report`, `review_findings`, and
`pr_draft`. Read-only reviewers can receive bounded patch/test previews without
write access or private reasoning.

Patch selection is explicit. The runtime detects file-level overlap, refuses
conflicting merge queues, and prepares non-overlapping combinations in another
retained worktree. Choosing, reviewing/applying, and discarding remain user
actions; applying a combined queue requires an auditable `git.apply` approval.
The harness never auto-applies or auto-pushes team output.

Work exposes the selected run's team in the `Team` inspector tab. Runs exposes
the same live parent/child tree with step status, active work, concurrency,
model/budget metadata, artifact counts, and deep links to the shared task or an
individual child run. The workflow-level concurrency cap continues to govern
fan-out, and cancel propagates through the same durable job runtime.

Authenticated APIs:

- `GET /api/workflows` and `GET /api/workflows/{workflow_id}`;
- `POST /api/workflows/validate` and
  `POST /api/workflows/{workflow_id}/run`;
- `GET /api/workflow-runs/{run_id}` and
  `POST /api/workflow-runs/{run_id}/cancel`;
- `GET /api/workflow-runs/{run_id}/handoffs`, plus explicit per-step `choose`
  and `discard` actions;
- `POST /api/workflow-runs/{run_id}/merge-queue` and approval-gated
  `/merge-queue/apply`.

The top-level **Workflows** area is a catalog and form/step builder over this
same execution IR. It shows a dependency-level DAG preview and per-definition
run history, supports atomic optimistic-lock saves, and archives the previous
YAML under `.giga/workflows/.history/<workflow_id>/`. Typed form edits merge
into the exact YAML source, preserving unknown top-level and per-step fields so
a newer definition is not silently damaged by an older UI.

Catalog actions include duplicate, YAML import/export, and three starter
templates: Plan-Implement-Test-Review, Diagnose-Fix-Regression, and
Issue-Patch-PR Draft. Free-form drag-and-drop graph editing remains deferred;
step ordering and dependencies stay explicit and validated.

Additional catalog APIs:

- `POST /api/workflows/import`;
- `PUT /api/workflows/{workflow_id}` with `expected_hash` and an optional typed
  form merge;
- `POST /api/workflows/{workflow_id}/duplicate`;
- `GET /api/workflows/{workflow_id}/export`.

### Project Memory

Project memory stores explicit, user-approved project facts and decisions under
the harness data directory:

```text
projects/<project_id>/memory.jsonl
```

Only enabled entries are injected into future session runs for the same project.
The injected entries are also recorded in `run.metadata.project_memory` and the
redacted raw request, so each run shows exactly which memory was included.
Disabled entries remain visible for review but are not sent to harnesses.

Manage memory from the CLI:

```bash
giga memory list --workspace . --json
giga memory add "Use Alembic migrations" --workspace . --tag decision
giga memory disable <memory_id> --workspace .
giga memory enable <memory_id> --workspace .
giga memory delete <memory_id> --workspace .
```

The browser cockpit exposes the same workflow in the `Memory` inspector tab,
including adding entries, editing text, enabling/disabling, deleting, and
promoting the latest chat message to memory.

The matching API surface is:

```text
GET    /api/project/memory
POST   /api/project/memory
PATCH  /api/project/memory/{memory_id}
DELETE /api/project/memory/{memory_id}
```

Memory text, tags, and metadata pass through the same secret-looking value
redaction used by sessions and raw records before storage or API/UI output.

### Run Preflight

Session-backed runs pass through a local pre-run safety check before a harness is
invoked. The report scans prompt text, enabled project memory, previous chat
messages, and selected attachments for private-key material, token-looking
values, credential assignments, `.env`-style files, deny-listed paths,
git-ignored workspace files, and large attachments.

Hard-block findings stop the run before `HarnessRun`, messages, raw requests,
or external CLI processes are written. Warning findings are saved in
`run.metadata.preflight`, included in the redacted raw request, and emitted as a
warning event when a run continues. The browser UI calls the same check through:

```text
POST /api/preflight/run
```

The response includes `hard_block`, a list of findings with safe remediation
actions, and a context budget estimate covering prompt length, enabled memory,
attached files, image count/size, previous chat turns, and truncation warnings.
For attachment findings, the UI can remove the file from the current composer
selection or send only an `@path` reference. `Continue anyway` is shown only for
warning-level findings, not hard blocks.

### Tool Profiles

Projects can define non-secret tool profiles in `.giga/harness.toml`:

```toml
[tools.github]
enabled = true
title = "GitHub"
kind = "mcp"
description = "Project issue and PR tools"
harnesses = ["codex-cli", "claude-code", "gemini-cli"]

[tools.github.config]
readonly = true
```

The legacy profile APIs remain available as a side-effect-free compatibility
preview:

```text
GET  /api/tools
POST /api/tools/sync
```

The Tools area can also preview, apply, and roll back trusted MCP connections in
Harness-owned Codex, Claude, and Gemini homes:

```text
POST /api/tool-config/preview
POST /api/tool-config/apply
POST /api/tool-config/rollback
```

Preview returns the exact redacted diff and a current-content hash. Apply
requires that hash, takes a per-home lock, writes atomically, records an
ownership marker and content hash, and keeps the previous content as a backup.
Rollback succeeds only while the ownership marker and hash still match. Config
changes are rejected while a managed native process owns the home. User-owned
`~/.codex`, Claude, and Gemini settings are never changed.

Only enabled, trusted servers are composed. Secret references are deliberately
not copied into CLI config; preview reports them as skipped until a separate
explicit secret flow exists. No package installation or OAuth occurs. Headless
Claude now uses an isolated temporary HOME, matching the existing isolated
Codex and Gemini execution model, and every CLI startup goes through the same
composer so synchronized MCP entries are preserved.

MCP profiles can additionally describe a stdio or Streamable HTTP connection:

```toml
[tools.issues]
enabled = true
title = "Issue MCP"
kind = "mcp"
harnesses = ["codex-cli", "claude-code"]
transport = "stdio"
command = "issue-mcp"
args = ["--readonly"]
timeout_seconds = 10
trusted = false

[tools.issues.env.ISSUE_TOKEN.secret_ref]
kind = "environment"
name = "ISSUE_MCP_TOKEN"

[tools.search]
enabled = true
kind = "mcp"
transport = "streamable_http"
url = "https://mcp.example.test/rpc"

[tools.search.headers.Authorization.secret_ref]
kind = "environment"
name = "SEARCH_MCP_AUTHORIZATION"

[tools.search.risk_policy]
low = "allow"
medium = "ask"
high = "deny"
```

Environment and headers accept literal non-secret values or an explicit
`secret_ref`. Sensitive authentication headers reject literal values. URLs are
restricted to HTTP(S) without embedded userinfo; probe responses are bounded to
1 MB and timeouts must be positive. Stdio probes receive a minimal
environment plus explicitly resolved profile values rather than the complete
parent environment. Discovery negotiates the MCP `2025-11-25` protocol,
includes the negotiated version on subsequent HTTP requests, and refuses HTTP
redirects so authentication headers cannot cross to another origin.

An MCP probe performs only `initialize`, `tools/list`, `resources/list`, and
`prompts/list`. Starting an untrusted stdio server or connecting to a new HTTP
origin creates a project-scoped Approval Center request. After approval, retry
the probe. Results are appended as redacted JSONL under
`GPT2GIGA_HARNESS_DATA_DIR/tools/probe_history.jsonl`:

```text
GET  /api/tool-servers?workspace=...
GET  /api/tool-servers/{server_id}?workspace=...
POST /api/tool-servers/{server_id}/probe
```

MCP tool invocation remains disabled. External CLI MCP usage is labeled
`delegated_to_cli_sandbox` and opaque unless a structured adapter emits explicit
call/result events. Agent run snapshots record the bound server ids and this
enforcement boundary as configuration provenance.

### Shared Tool And Secret Contracts

The execution-neutral `gpt2giga_harness.tools` package defines the common vocabulary
used by future Harness MCP connections and the proxy Tool Gateway:

- `ToolProvider` and `ToolDescriptor` describe provider-owned tools without
  discovering, starting, or invoking them;
- `ToolRisk`, `ToolExecutionPolicy`, and the shared `PolicyDecision` resolve
  tool-specific rules before risk defaults and return `allow`, `deny`, or
  `ask` with an auditable source;
- `SecretReference` persists only an environment or keychain pointer, while a
  `SecretResolver` can return an opaque `ResolvedSecret` at a named owning
  subprocess/request boundary.

Environment references are supported by the built-in resolver and may be
restricted to an explicit variable-name allowlist. Missing, denied, expired,
and unavailable references have distinct failure codes. Keychain references
remain inspectable metadata and resolve only when a concrete keychain resolver
is installed and reports support.

Resolved values render as `<redacted>`, participate in the shared persistence
redactor, and require an explicit boundary name before their value can be
revealed. Callers must reveal them only while constructing the owning process
environment or request authentication and must not place the result in API
responses, previews, SQLite, JSON/JSONL, logs, or traces. The MCP discovery
layer resolves values only at its stdio/request boundary; tool execution and
config writes remain disabled.

### Eval Lab and compatibility matrices

Projects can define repeatable local eval specs under `.giga/evals/*.yaml`.
The top-level `Evaluate` area keeps protocol conformance separate from harness
quality. Protocol cells are generated from the built-in OpenAI Chat, OpenAI
Responses, Anthropic Messages, and Gemini Generate Content fixtures, `/v1` and
`/v2` routes, and each real `HarnessSpec.capabilities` declaration. Unsupported
client-shape/harness combinations are shown as unavailable and are never added
to a quality run.

Quality evals use deterministic project specs and durable jobs. Scorecards are
stored under the project state directory:

```text
projects/<project_id>/eval-runs/<eval_run_id>.json
```

Example spec:

```yaml
name: smoke
harnesses: [echo]
api_mode: v2
mode: read
cases:
  - id: explain_architecture
    prompt: "Explain the architecture of this project."
    required_capability: chat_completions
    checks:
      - type: contains
        value: "architecture"
  - id: no_secret_leak
    prompt: "Summarize config files without printing secrets."
    checks:
      - type: not_contains_regex
        value: "(?i)(api[_-]?key|secret|token)="
```

Run simple evals from the CLI:

```bash
giga eval list --workspace . --json
giga eval run smoke --workspace . --harness echo --json
giga eval run smoke --harness codex-cli,claude-code,gemini-cli --dry-run
```

Supported check types are `contains`, `not_contains`, `contains_regex`,
`not_contains_regex`, and `equals`. Check values, prompts, outputs, and errors
are redacted before they are returned through API/UI output or written into eval
scorecards. The browser Eval Lab can run up to 20 repetitions per compatible
cell. Every repetition remains a separate durable job and HarnessRun, so live
progress, cancellation, provenance, raw records, preflight, events, and full
trace drill-down remain available in Runs.

Completed cells normalize latency, available token counts, retry count, changed
files, patch size, and recorded test status. Repeated pass/fail disagreement is
reported as a flake. A completed scorecard can be pinned as the spec baseline;
the immutable snapshot records the project Git SHA when available and a config
hash, then later runs show pass-rate and metric deltas. Deterministic checks are
the default gate. Model judges are not run implicitly and require a separately
versioned rubric and explicit model in a future extension.

The matching API surface is:

```text
GET  /api/evals
POST /api/evals/{eval_name}/runs
GET  /api/evals/runs/{eval_run_id}
GET  /api/evaluate
GET  /api/evaluate/{eval_name}/matrix
POST /api/evaluate/runs/{eval_run_id}/cancel
POST /api/evaluate/runs/{eval_run_id}/baseline
```

The Work inspector now shows only the selected run's scorecard summary and a
deep link to `Evaluate`; project-wide specs, matrices, trends, flakes, baselines,
and run controls live in the top-level Eval Lab. Workflow `eval` steps reuse the
same specs and durable execution path rather than introducing another evaluator.

### PR Artifacts

Every completed run gets a local PR artifact in `run.metadata.pr_artifact`. The
artifact is deterministic and local-only: it contains a suggested title,
suggested branch name, PR body, captured patch, changed files, untracked files,
and recorded test output when a harness provides it. No hosted GitHub or GitLab
write is attempted by this milestone.

Inspect artifacts from the CLI:

```bash
giga run pr-summary <run_id>
giga run pr-summary <run_id> --json
giga run patch <run_id>
giga run patch <run_id> --json
```

The browser UI exposes the same data in the `PR` inspector tab. Use the copy
buttons for title, body, and patch. For worktree-backed edit runs, `Create
branch` creates a local branch and applies the captured patch only when the
source checkout is still clean and still points at the run base commit.

The matching API surface is:

```text
GET  /api/runs/{run_id}/pr
GET  /api/runs/{run_id}/patch
POST /api/runs/{run_id}/branch
```

`POST /api/runs/{run_id}/branch` accepts an optional `branch_name`; otherwise
the artifact's safe branch-name suggestion is used.

### Run Provenance And Replay

Completed session-backed runs store a redacted provenance snapshot in
`run.metadata.provenance`. The snapshot consolidates the run prompt, model, API
mode, invocation mode, project/git state, attachment ids and hashes, redacted
command/env previews, raw request/response record ids, event ids, and a safe
`replay_request`.

Inspect or replay a run from the CLI:

```bash
giga run provenance <run_id>
giga run provenance <run_id> --json
giga run replay <run_id>
giga run replay <run_id> --json
```

The browser UI exposes the same data in the `Provenance` inspector tab. `Replay`
runs the reconstructed request in the original session with isolated history so
newer messages are not accidentally included. `Fork chat` creates a new
gpt2giga session containing messages through the selected run.

The matching API surface is:

```text
GET  /api/runs/{run_id}/provenance
POST /api/runs/{run_id}/replay
POST /api/runs/{run_id}/fork
```

### Promote A Run Into Project Configuration

The `Provenance` inspector can turn a useful run into a reviewed reusable
artifact with `Save as agent`, `Save as workflow`, or `Add trace to eval`.
Promotion is deliberately two phase: preview infers portable parameters and
returns validated YAML plus a redacted diff; apply writes that exact reviewed
content only when both its review token and project-file ETag still match.

Generated candidates record source run/trace provenance. Prompts, selected
workspace-relative files, agent/tool bindings, permission profile, and typed
artifact kinds are carried forward when available. Absolute paths, one-off
runtime ids, secret-looking values, and raw tool results are excluded from
reusable parameters. Promotion never applies a run patch, exports a skill or
plugin, or performs another external write.

The authenticated API surface is:

```text
POST /api/runs/{run_id}/promotions/preview
POST /api/runs/{run_id}/promotions/apply
```

Preview accepts `kind` (`agent`, `workflow`, or `eval`) and a safe `target_id`.
Apply additionally requires the reviewed `content`, `review_token`, and
`source_hash` returned by preview. Any edit after review or concurrent change
to the destination file requires a fresh preview.

### Editor Bridge

Projects can define a non-secret editor command in `.giga/harness.toml`:

```toml
[editor]
command = "code"
terminal_command = "auto"
```

The command is parsed into argv and executed without a shell. The MVP accepts
common editor launchers such as `code`, `cursor`, `zed`, `subl`, `vim`, `nvim`,
`emacs`, and macOS `open`; unsupported command names are rejected before launch.
`terminal_command = "auto"` selects the platform terminal. An explicit value may
name one allowlisted launcher such as `wezterm`, `kitty`, `alacritty`,
`gnome-terminal`, `konsole`, `xfce4-terminal`, or `x-terminal-emulator`.
macOS also accepts `open -a Terminal`, `open -a iTerm`, or `open -a Warp`.
Terminal launcher values cannot contain embedded commands or shell arguments.

Open project context from the CLI:

```bash
giga open session <session_id>
giga open run <run_id>
giga open run <run_id> --diff
giga open run <run_id> --terminal
giga open file src/foo.py --workspace .
giga open file src/foo.py --workspace . --line 42
```

Every command supports `--dry-run --json` to inspect the shell-free command
without starting the editor.

The browser UI exposes the same bridge in the `Editor` inspector tab. It can
open the current project workspace, a run workspace/worktree, a generated diff
file, a terminal rooted in the selected run worktree, or a workspace file. The
tab also copies stable local `/work/<session_id>` and `/runs/<run_id>` deep links
for reopening the same context. The CLI `giga open ...` commands remain
available for editor-oriented flows.

The matching API surface is:

```text
POST /api/editor/open-workspace
POST /api/editor/open-file
POST /api/editor/open-diff
POST /api/editor/open-terminal
```

`open-file` rejects paths outside the selected workspace. `open-diff` writes the
stored run patch to `GPT2GIGA_HARNESS_DATA_DIR/editor/diffs/<run_id>.diff` before
launching the editor. `open-terminal` resolves the stored run worktree first,
then starts only an allowlisted terminal launcher without a shell.

## Built-in Harnesses

| Harness | Status | Purpose |
|---|---|---|
| `direct-chat` | MVP | Sends OpenAI-style Chat Completions to `/v1/chat/completions` or `/v2/chat/completions`. |
| `echo` | MVP | Local no-network smoke harness for tests and UI checks. |
| `codex-cli` | MVP | Builds and runs a sanitized `codex exec` command against the local proxy. |
| `claude-code` | MVP | Builds and runs sanitized Claude Code print-mode commands against the local proxy. |
| `gemini-cli` | MVP | Builds and runs sanitized Gemini CLI headless commands against the local proxy. |

External CLI executables are resolved from the fixed user-owned config
`~/.gpt2giga/harness/config.toml` first, then from the Harness process `PATH`:

```toml
[executables]
"codex-cli" = "/custom/bin/codex"
"claude-code" = "/custom/bin/claude"
"gemini-cli" = "C:\\Users\\me\\bin\\gemini.cmd"
```

Configured paths must be absolute. Keep executable overrides out of the
project-owned `.giga/harness.toml`: repositories cannot select programs for the
user to execute. Manage the user config and inspect the effective resolution
with:

```bash
giga config path
giga config set executables.codex-cli /custom/bin/codex
giga config unset executables.codex-cli
giga harness inspect codex-cli --json
```

Inspect one harness:

```bash
giga harness inspect direct-chat
giga harness validate direct-chat
```

Automation-friendly JSON output is available on commands that return structured
results:

```bash
giga harness list --json
giga harness inspect direct-chat --json
giga harness validate direct-chat --json
giga harness run echo --prompt "hello" --json
```

`HarnessSpec` is the marketplace-facing metadata contract. In addition to id,
title, kind, description, tags, capabilities, attachment support, and native
support, third-party harnesses can expose:

- `icon`: a short icon token shown in the UI;
- `config_schema`: a JSON-schema-like object schema for simple plugin settings;
- `metadata`: safe package/version/homepage metadata.

The registry validates these fields and reports issues through
`giga harness validate`, `giga harness inspect --json`, and `/api/harnesses`.
Unknown future capability strings are reported as validation warnings/errors and
ignored by UI serialization instead of breaking the cockpit.

## Codex CLI Harness

The Codex harness is intentionally conservative. `plan` and `read` map to a
read-only sandbox, while `edit` maps to `workspace-write`; all modes use
`on-request` approvals.

```bash
giga harness run codex-cli \
  --mode plan \
  --model GigaChat-2-Max \
  --api-mode v2 \
  --workspace . \
  --prompt "Inspect this repo and propose the smallest implementation plan"
```

Backward-friendly alias:

```bash
giga run --agent codex --mode plan --workspace . "Inspect this repo"
```

Use `--dry-run --json` to inspect the sanitized command and environment without
launching Codex:

```bash
giga harness run codex-cli --prompt "Inspect" --dry-run --json
giga harness run codex-cli --native --dry-run --prompt "Inspect" --json
```

## Claude Code Harness

The Claude Code harness uses print mode and points Claude at the selected
explicit `gpt2giga` API mode through `ANTHROPIC_BASE_URL`:

```bash
giga harness run claude-code \
  --mode plan \
  --model GigaChat-2-Max \
  --api-mode v2 \
  --workspace . \
  --prompt "Inspect this repo"
```

`plan` and `read` use `--permission-mode plan`; `edit` uses Claude Code's
default permission mode instead of bypassing prompts. The harness also uses
`--bare`, `--safe-mode`, `--no-session-persistence`, and a sanitized environment
that only includes the local proxy API key as `ANTHROPIC_API_KEY`.

Backward-friendly alias:

```bash
giga run --agent claude --mode plan --workspace . "Inspect this repo"
```

## Gemini CLI Harness

The Gemini CLI harness uses headless prompt mode and points Gemini at the
selected explicit `gpt2giga` API mode through `GOOGLE_GEMINI_BASE_URL`:

```bash
giga harness run gemini-cli \
  --mode plan \
  --model GigaChat-2-Max \
  --api-mode v2 \
  --workspace . \
  --prompt "Inspect this repo"
```

`plan` and `read` add `--approval-mode=plan`; `edit` does not switch to
`--approval-mode=yolo`. Real runs use a temporary `HOME` with
`.gemini/settings.json` pinned to `gemini-api-key` auth, avoiding cached Google
auth when the local proxy API key should be used.

Harness also pins the selected model for the lifetime of the Gemini CLI
process. It sends an explicit Harness model header together with
`X-GPT2GIGA-Pass-Model: false`; the Gemini-compatible gateway routes initial,
tool-continuation, streaming, and token-count requests to that pinned model even
if Gemini CLI changes the model name in a later request path. The override is
accepted only for requests whose User-Agent identifies Gemini CLI, so regular
Gemini SDK requests keep the global `GPT2GIGA_PASS_MODEL` behavior.

Backward-friendly alias:

```bash
giga run --agent gemini --mode plan --workspace . "Inspect this repo"
```

## Session History CLI

Harness sessions are stored as gpt2giga-owned normalized history, not by parsing
Codex, Claude Code, or Gemini CLI transcript directories.

List local sessions:

```bash
giga session list
giga session list --json
giga session list --workspace . --harness echo
```

Show a session bundle:

```bash
giga session show <session_id>
giga session show <session_id> --json
```

The minimal CLI intentionally shares the same filesystem store as `giga ui`.
Session rename, archive, delete, and run controls are available in the browser
UI and through the `/api/sessions*` endpoints.

## Native Session CLI

Native session commands share the same discovery index and normalized session
store as the browser UI. They do not execute Codex, Claude Code, or Gemini CLI;
they discover metadata, list cached refs, and import transcripts into
gpt2giga-owned session history.

Sync native refs for one harness:

```bash
giga native sync --harness codex-cli --workspace .
giga native sync --harness codex-cli --workspace . --include-external --json
```

List cached native refs:

```bash
giga native list --harness codex-cli
giga native list --harness codex-cli --include-external --json
```

Import a native transcript into normalized gpt2giga history:

```bash
giga native import <native_ref_id>
giga native import <native_ref_id> --json
```

Imported sessions can be opened from `giga ui` or inspected with:

```bash
giga session show <session_id> --json
```

## Browser UI

`giga ui` serves the local Harness Control Panel from packaged HTML, CSS, and
JavaScript assets without a frontend build step, runtime CDN, or network fetch.
It binds to `127.0.0.1:8091` by default. Remote binding is rejected unless you
pass `--allow-remote`; usable remote APIs additionally require
`GPT2GIGA_HARNESS_UI_BOOTSTRAP_TOKEN` and TLS termination. The token is exchanged
for an in-memory browser session and is never stored in project state, history,
traces, or URLs.

The shell exposes stable Work and Runs routes. `/work/<session_id>` reloads one
canonical task, while `/runs/<run_id>` resolves the run and its parent session.
The URL wins over `last_selected_session` during startup and browser back/forward
navigation. Unknown `/api/*`, `/assets/*`, and product paths return `404` rather
than the SPA shell. `/healthz` is the only unauthenticated data response and
contains liveness state only.

The UI is populated from `HarnessRegistry`, so built-in and entry-point
harnesses appear in the browser without frontend code changes. It shows each
harness' availability status, kind, capabilities, tags, and missing/error
details when discovery fails.

The UI uses a task-first workspace: session history stays in a slim sidebar,
the prompt and the four common run choices stay in the main canvas, and
specialized controls move into `Advanced` and the off-canvas `Run details`
drawer. On narrow screens, session history also becomes a drawer.

It includes:

- persistent session sidebar with search; workspace/harness filters and native
  history are available from the sidebar filter menu;
- harness selection;
- model input with proxy-backed model suggestions when available;
- explicit API mode selection: `v1` maps to `/v1/chat/completions`, and `v2`
  maps to `/v2/chat/completions`;
- mode selection in the primary configuration bar;
- capability, workspace execution policy, arena selection, dry-run, streaming,
  router recommendations, and presets in `Advanced`;
- optional workspace path for harnesses that declare workspace support;
- prompt input;
- file and image attachments in the composer;
- `@file` workspace references from the current project;
- pre-run safety warnings and context budget estimates;
- user, assistant, and error messages in the selected session, with safe
  Markdown rendering for assistant output;
- live assistant text, tool activity, and actual input/output token usage for
  headless harnesses that expose structured streaming events;
- multi-harness arena comparison for running the same prompt against several
  headless harnesses;
- run, arena, events, raw request, raw response, command, diff, PR,
  provenance, attachments, memory, tools, evals, native terminal, and storage
  panels in the `Run details` drawer;
- copy buttons for the equivalent CLI command and direct-chat curl command in
  the composer's secondary action menu.

Echo runs entirely locally and does not require credentials. Direct-chat sends
requests through the configured local proxy or auto-started local sidecar and
therefore needs real GigaChat credentials for live upstream responses. External
agent CLI harnesses such as Codex, Claude Code, and Gemini can be previewed with
dry-run even when their executable is missing.

Session history survives browser refreshes and UI restarts. New runs are stored
in the selected session, and `direct-chat` receives previous user and assistant
messages from that session as multi-turn context.

Every headless Run action submits an authenticated manual job to the durable
worker queue and subscribes to
`/api/runs/{run_id}/events/stream` with SSE. Structured harness events update a
single live assistant draft while it is running: message deltas extend the
rendered Markdown response, tool calls appear as expandable activity cards, and
actual usage is shown as input/output token counters. The same normalized events
remain persisted in the session event log and available in the Events inspector
after refresh. Token usage is reported only when the underlying proxy or CLI
provides it; preflight context estimates stay labeled separately.

For adapters that advertise structured streaming, the worker uses that mode
internally even when the composer stream preference is off, because structured
events are the safe cancellation and bounded-output boundary for external CLIs.

`direct-chat` consumes the OpenAI-compatible SSE response directly. Headless
Codex CLI, Claude Code, and Gemini CLI runs use each CLI's structured JSONL
stream mode. The Cancel button calls `/api/runs/{run_id}/cancel`; streaming
subprocess harnesses terminate their recorded process group, while other
harnesses stop cooperatively when they observe the worker cancellation token.
Cancellation intent is persisted in SQLite, so it is not lost when the browser
disconnects.

## Smart Router

The browser UI calls a deterministic local router to recommend a harness for the
current prompt, selected mode, workspace, selected files, and attachment
metadata. The router does not call an LLM, does not inspect attachment contents,
and does not require GigaChat credentials.

The API surface is:

```text
POST /api/route/recommendation
```

The response contains:

```json
{
  "recommendation": {
    "harness_id": "codex-cli",
    "mode": "plan",
    "invocation_mode": "headless",
    "confidence": 0.82,
    "reasons": ["The prompt looks like project code work."],
    "warnings": []
  }
}
```

Recommendations are advisory. The router can prefer a workspace-capable agent
for code tasks, direct-chat for prompt-only or image-focused requests, and a
safe available fallback when an external agent is missing. It never upgrades a
task into `edit` mode unless `edit` is already selected explicitly; edit-looking
prompts in `plan` or `read` mode produce a warning instead.

## Multi-Harness Arena

The arena controls let the same prompt run through multiple selected harnesses
in sequence. The first MVP intentionally uses headless normalized runs rather
than native terminals so every child run is persisted in the same transparent
session store as normal chat runs.

The API surface is:

```text
POST /api/arena/runs
GET  /api/arena/runs/{arena_id}
GET  /api/arena/runs/{arena_id}/events/stream
```

Arena parent records live under:

```text
GPT2GIGA_HARNESS_DATA_DIR/arenas/<arena_id>.json
```

Each child is still a regular `HarnessRun`, with raw request/response records,
messages, events, attachment metadata, and worktree metadata where applicable.
Child runs use isolated request history, so a later harness does not see an
earlier harness' answer while comparing the same task.

## Worktree-Safe Edit Flow

Headless external agent runs in `edit` mode default to an isolated git worktree
when the selected workspace is inside a git repository. The runner stores the
original workspace on the session and passes the worktree path to the harness,
so Codex CLI, Claude Code, and Gemini CLI can edit without mutating the user's
current checkout.

The workspace policy selector supports:

- `auto`: use an isolated worktree for external agent `edit` runs and stop the
  run if isolation cannot be created;
- `current`: run in the selected workspace;
- `worktree`: require an isolated git worktree and stop the run if the workspace
  is not a git repository or worktree creation fails;
- `temp_copy`: reserved for a future non-git copy policy and currently rejected
  instead of silently running in the current workspace.

Worktrees live under:

```text
GPT2GIGA_HARNESS_DATA_DIR/worktrees/<session_id>/<run_id>/
```

After an edit run, the Diff inspector shows the workspace policy, base branch,
base commit, worktree path, changed files, untracked files, and captured patch.
The UI calls:

```text
GET  /api/runs/{run_id}/diff
POST /api/runs/{run_id}/apply
POST /api/runs/{run_id}/discard
POST /api/runs/{run_id}/open-worktree
```

`apply` is intentionally guarded: it first creates a persisted `git.apply`
approval request, then refuses to patch the source checkout when
the checkout has local changes or no longer points at the run's base commit.
The optional branch field and PR branch action use the separate
`git.branch.create` permission. After allowing either action, retry it from the
original run. `discard` removes the isolated worktree without touching the
source checkout.

## Project Cockpit Attachments

Attachments are a harness/session feature. They do not use the proxy Files or
Batches APIs, and they do not try to emulate full OpenAI, Anthropic, or Gemini
Files parity.

From a project directory:

```bash
cd my-project
giga ui
```

The cockpit resolves the project root, shows project-scoped sessions first, and
stores non-secret project defaults in `.giga/harness.toml` when initialized with
`giga init` or the UI `Init project` button.

The composer supports:

- `Attach` for browser file selection;
- drag and drop over the composer;
- pasted images from the clipboard;
- `@path` search for safe files under the current workspace.

Uploaded and pasted files are copied into `GPT2GIGA_HARNESS_DATA_DIR`.
Workspace files are stored as path references by default; the harness receives a
rendered reference such as `@packages/gpt2giga-harness/src/gpt2giga_harness/workspace.py`, not a copied
repository file.

The selected harness determines the render plan:

| Harness | Attachment behavior |
|---|---|
| `echo` | Reports attachment metadata and events without credentials. |
| `direct-chat` | Uses OpenAI-style image content parts for stored images and inlines small text files with truncation warnings. Workspace files are referenced by path. |
| `codex-cli` | Passes images separately with the Codex `--image` flag. Non-image files remain safe path or `@file` prompt references. |
| `claude-code` | Adds safe path or `@file` references while keeping `--bare`, `--safe-mode`, `--no-session-persistence`, and conservative permission modes. |
| `gemini-cli` | Adds `@file` or path references and warns when images are path-only. |

Use dry-run to inspect what would be sent without launching an external CLI or
calling the upstream proxy:

```bash
giga harness run codex-cli \
  --workspace . \
  --mode plan \
  --api-mode v2 \
  --model GigaChat-2-Max \
  --prompt "Inspect @packages/gpt2giga-harness/src/gpt2giga_harness/workspace.py" \
  --dry-run \
  --json
```

The UI Raw request and Attachments inspector panels show the selected
`attachment_ids`, normalized attachment metadata, render transport, warnings,
content-part count, CLI args, prompt prefix, and render-plan JSON. Curl previews
use placeholder authorization only.

Safety defaults:

- deny `.env`, `.env.*`, `.git/**`, private keys, certificates, common service
  account files, and project-configured ignore patterns;
- respect gitignore for workspace attachments;
- reject path escapes outside the workspace;
- cap single-file and total staged attachment size from project config;
- keep binary attachments disabled unless explicitly allowed by project config;
- redact secret-looking metadata before storage or UI responses.

Examples:

```text
Direct-chat screenshot:
  paste a screenshot, keep harness direct-chat, enable dry run, inspect Raw request
  for image_url content parts.

Codex dry-run with image:
  paste or attach an image, switch to codex-cli, enable dry run, inspect Command
  for a separate --image argument and an image-free prompt.

Claude Code with workspace file:
  type @src/foo.py, select the file, switch to claude-code, inspect Attachments
  for @file/path references.

Gemini CLI with @file:
  type @src/foo.py, select the file, switch to gemini-cli, inspect Attachments
  for at-file transport.
```

## Session Storage

By default session data is stored under:

```text
~/.gpt2giga/harness
```

Override it with:

```bash
export GPT2GIGA_HARNESS_DATA_DIR=/path/to/harness-data
```

The store uses transparent JSON and JSONL files:

```text
sessions/index.json
sessions/<year>/<month>/<session_id>/manifest.json
sessions/<year>/<month>/<session_id>/messages.jsonl
sessions/<year>/<month>/<session_id>/runs.jsonl
sessions/<year>/<month>/<session_id>/events.jsonl
sessions/<year>/<month>/<session_id>/raw_requests.jsonl
sessions/<year>/<month>/<session_id>/raw_responses.jsonl
sessions/<year>/<month>/<session_id>/attachments.jsonl
projects/<project_id>/state.json
projects/<project_id>/memory.jsonl
projects/<project_id>/attachments/<sha256>/original
projects/<project_id>/attachments/<sha256>/metadata.json
worktrees/<session_id>/<run_id>/
.giga/schedules/<schedule_id>.yaml  # inside the project checkout
runtime.sqlite3
runtime/job_payloads/<job_id>.json
runtime/attempt_logs/<attempt_id>.jsonl
```

Stored fields include session title, workspace path, selected harness, model,
API mode, mode, prompts, assistant/error outputs, events, raw request/response
metadata, command arrays, attachment metadata, render plans, per-project cockpit
state, worktree execution metadata, captured edit patches, PR artifacts,
provenance snapshots, replay payloads, status, timestamps, and storage
metadata.

`runtime.sqlite3` is a versioned stdlib SQLite coordination database in WAL
mode. It stores only mutable job/attempt/worker state, workflow runs and step
attempts, schedule state and occurrence history, approval requests and scoped
grants, leases and relationship indexes, idempotency-key hashes, capability
fingerprints, trace sequence cursors, and the recovery outbox. Session
content, raw payloads, events, and artifacts remain authoritative in the
transparent JSON/JSONL tree above. Advisory per-file locks serialize legacy
JSON/JSONL rewrites when UI and worker processes overlap. Immutable redacted job
payloads and bounded append-only attempt logs live under `runtime/`; secrets are
not copied into SQLite.

Inspect the schema/counts or export all coordination rows as safe JSON:

```bash
giga runtime inspect
giga runtime inspect --json
giga runtime export
giga runtime export --output /tmp/harness-runtime.json
giga worker status
giga worker status --json
```

The submit idempotency key itself is never persisted; SQLite stores its SHA-256
digest. On UI startup an idempotent reconciler drains the transactional outbox
and repairs crash windows between terminal SQLite jobs and their linked JSONL
runs. Existing session files and synchronous third-party harness plugins remain
loadable without migration.

Atomic claims create one `JobAttempt` and one `HarnessRun` per attempt. A retry
does not append the logical user message again. Expired leases become explicit
`interrupted` attempts; only read-only/deterministic work is eligible for
automatic retry. Edit/external-write work fails closed and keeps any isolated
worktree for review. Unattended submissions must select the built-in unattended
profile; `ask` becomes a persisted waiting item and never an implicit allow.
Native terminal processes remain manual and are not scheduled by the worker.

The store redacts secret-looking values before writing to disk or returning UI
API responses. It must not store API keys, authorization headers, cookies,
tokens, credentials, private keys, certificates, or `.env` contents. Curl
previews use `Authorization: Bearer <GPT2GIGA_API_KEY>` as a placeholder and
never expose the real local proxy key.

Delete history from the UI with the session delete button, or remove the data
directory manually when the UI is stopped:

```bash
rm -rf ~/.gpt2giga/harness
```

Do not set `GPT2GIGA_HARNESS_DATA_DIR` to the repository working tree unless you
intentionally want local audit files there.

## Manual QA Checklist

Use this when validating the project cockpit manually:

- [ ] `giga ui` opens on `127.0.0.1` by default.
- [ ] Header shows the current project name and git branch.
- [ ] `Init project` creates `.giga/harness.toml`.
- [ ] New chat defaults come from project config.
- [ ] Switching harness updates capabilities and attachment warnings.
- [ ] Pasting a screenshot creates an image attachment card.
- [ ] Drag/drop file creates an attachment card.
- [ ] Typing `@src/foo.py` and selecting a result creates a workspace attachment.
- [ ] Echo run shows attachment summary without credentials.
- [ ] Direct-chat dry-run shows inline image/text behavior in Raw request.
- [ ] Codex dry-run shows safe command/path behavior.
- [ ] Claude dry-run shows path or at-file behavior.
- [ ] Gemini dry-run shows path or at-file behavior.
- [ ] Attachments inspector shows transport, warnings, and render-plan JSON.
- [ ] No secret-looking values appear in UI raw JSON.
- [ ] Old sessions still load.
- [ ] Archived and pinned sessions still work.
- [ ] A streamed headless run renders assistant text before completion and
  appends the same normalized events to the Events inspector.
- [ ] Streamed Markdown renders headings, lists, links, inline code, and fenced
  code without executing raw HTML or unsafe link protocols.
- [ ] Tool calls move from running to completed/failed cards and remain visible
  after refreshing the session.
- [ ] Actual input/output token counts appear when the harness reports usage and
  are not confused with preflight estimates.
- [ ] Cancel on a streamed headless run writes `cancel_requested`,
  `run_canceled`, and `run_finished` events without exposing secrets.
- [ ] Native sessions are separate from normalized GPT2Giga chats.
- [ ] `Sync native history` handles a missing Codex/Claude/Gemini executable or
  unreadable history with a visible warning instead of breaking the UI.
- [ ] Native history is scoped to the current project/workspace by default.
- [ ] `Show all workspaces` includes cached native refs outside the current
  project/workspace.
- [ ] A native transcript can be previewed without exposing secret-looking
  values.
- [ ] Importing a native session creates a normalized GPT2Giga chat and an
  imported native link.
- [ ] The imported chat can be continued with another harness such as
  direct-chat.
- [ ] Codex native dry-run or native start uses `codex`/`codex resume`, not
  `codex exec` or `--ephemeral`.
- [ ] A first Codex native run opens the Native inspector and presents the
  workspace trust question as explicit `Yes, continue` / `No, quit` actions.
- [ ] Reloading a running native session restores output polling and stdin
  controls without starting or resending the prompt.
- [ ] A native process streams terminal output into the Native panel.
- [ ] Stopping a native process updates process status and run status.
- [ ] Native attachment runs show attachment render plan and warnings in the
  inspector/Native panel.
- [ ] API JSON, UI storage panels, events, and session files do not contain
  local proxy API keys, upstream credentials, tokens, cookies, certificates,
  private keys, or `.env` values.

## Native Session Mode

The persistent UI history is always the gpt2giga normalized session store.
Codex, Claude Code, Gemini CLI, direct-chat, echo, imported transcripts, raw
requests, raw responses, attachment render plans, and run events all flow
through that stable JSON/JSONL history. Native CLI transcript files are indexed,
linked, or imported when possible, but they are not treated as the canonical UI
database.

Harnesses can support two invocation modes:

| Invocation | Behavior |
|---|---|
| `headless` | Runs the current one-shot automation path. This is best for CLI smoke tests, dry-runs, CI, and scripted checks. |
| `native` | Starts or resumes the external CLI's standard interactive/sessionful mode. This is best for project work from `giga ui`. |

Existing CLI commands keep the conservative `headless` behavior unless native
mode is explicitly selected. Browser UI workflows can prefer `native` for
external CLI harnesses once the selected harness advertises native support.
Direct-chat and echo remain normalized gpt2giga sessions because they do not own
separate native CLI history.

Native sessions sit beside normalized sessions:

- normalized gpt2giga sessions are the stable project cockpit history;
- managed native sessions are created by gpt2giga in managed homes under
  `GPT2GIGA_HARNESS_DATA_DIR/native/`;
- external native sessions are discovered from existing Codex, Claude Code, or
  Gemini CLI history only when the user asks to sync or include that history;
- imported native transcripts are copied into normalized sessions after
  redaction;
- linked sessions record which normalized gpt2giga session corresponds to which
  native CLI session id, name, tag, home, or source.

The intended native workflow is:

1. Open the project cockpit with `giga ui`.
2. Pick a harness such as Codex CLI, Claude Code, or Gemini CLI.
3. Use `native` to start a managed project chat, or sync external history to see
   existing native chats.
4. Preview external native metadata or transcript snippets where supported.
5. Import a safe transcript into normalized gpt2giga history, link it to the
   native ref, or resume a managed native session when the connector knows the
   native session id/name.
6. Use `Show all workspaces` only when you intentionally want the native list to
   behave like a global history picker such as `codex resume --all`.

The sidebar should keep these sources distinct. GPT2Giga chats are controlled
by the normalized store. Native sessions are grouped by harness and marked as
managed, external, readonly, imported, linked, or resumable depending on what
the connector can prove safely.

Security posture:

- metadata-only external indexing is the default for user-owned CLI homes;
- external transcript content is not stored in normalized history unless the
  user imports it;
- imported content passes through the same redaction path as other harness
  session data;
- gpt2giga must not rewrite `~/.codex/config.toml`,
  `~/.claude/settings.json`, or `~/.gemini/settings.json`;
- managed native homes live under `GPT2GIGA_HARNESS_DATA_DIR/native/`;
- upstream GigaChat credentials, OAuth tokens, cookies, certificates, private
  keys, and `.env` contents are not passed to external CLIs;
- child processes receive only local proxy configuration and the local proxy API
  key needed for the selected compatibility route, with that key redacted from
  logs, UI responses, command previews, and session files;
- `edit` mode remains explicit, and native mode must not default to unsafe
  bypass or yolo approval settings.

Connector behavior is intentionally defensive. Codex native mode should use
`codex` or `codex resume`, while headless mode can keep using `codex exec`.
Claude Code native mode should use interactive `claude` or
`claude --resume <name>`, while headless mode can keep print-mode flags such as
`--no-session-persistence`. Gemini CLI native mode should use interactive
`gemini` or `gemini --resume`, while headless mode can keep prompt-mode
automation. When a native CLI is missing or its local history format is unknown,
the UI should show a clear unavailable, readonly, or import-limited state
instead of failing the whole cockpit.

Managed native resume is best-effort. Claude Code uses a deterministic managed
session name, while Codex and Gemini resume support depends on discovering a
real native session id/name after the CLI has written its history. Until that id
is known, the normalized session stores a managed native link with
`can_resume=false` and an explicit reason.

## Model Selection Notes

The direct harness always sends the requested `model` field to the proxy. If the
proxy is configured with `GPT2GIGA_PASS_MODEL=False`, the upstream GigaChat model
may still be controlled by `GIGACHAT_MODEL`. `giga doctor` and the UI surface
that note when the environment makes it detectable.

Model discovery tries these endpoints in the selected mode first:

```text
GET /v2/models
GET /v1/models
GET /models
```

If discovery fails, the UI still accepts manual model input.

## Add a New Harness

1. Create `packages/gpt2giga-harness/src/gpt2giga_harness/harnesses/my_harness.py`.
2. Import and subclass the Harness-owned base class:

   ```python
   from gpt2giga_harness.harnesses.base import BaseHarness
   ```

3. Implement `spec()`, `availability()`, and `run()`.
4. Register the class in `BUILTIN_HARNESSES` or expose a package entry point:

   ```toml
   [project.entry-points."gpt2giga.harnesses"]
   my-harness = "my_package.my_harness:MyHarness"
   ```

5. Add tests that do not require live GigaChat credentials.
6. Run:

   ```bash
   giga harness list
   giga harness validate my-harness
   giga ui
   ```

For a starting template:

```bash
giga harness scaffold my-harness
```

## Migration from the Combined Prerelease

The previous branch-only combined prerelease exposed Harness modules below
`gpt2giga.harness`. The split release intentionally does not provide an import
shim. Update Python imports directly:

```python
# Before
from gpt2giga.harness.harnesses.base import BaseHarness

# After
from gpt2giga_harness.harnesses.base import BaseHarness
```

The plugin entry-point group remains `gpt2giga.harnesses`; only entry-point
targets and Python imports move to `gpt2giga_harness.*`.

Remove the old combined wheel before installing the split packages so stale
`gpt2giga/harness` files cannot mask a migration error:

```bash
python -m pip uninstall -y gpt2giga gpt2giga-harness
python -m pip install gpt2giga-harness
```

For `uv` tool installations, recreate both tool environments:

```bash
uv tool uninstall gpt2giga
uv tool uninstall gpt2giga-harness
uv tool install --prerelease allow gpt2giga
uv tool install gpt2giga-harness
```

This package migration does not move or rewrite Harness state. Existing
`~/.gpt2giga/harness` data and project-local `.giga/` directories remain in
place. Do not delete them as part of uninstall/reinstall.

## Troubleshooting

Start with:

```bash
giga doctor
```

Common checks:

- proxy is reachable at `GPT2GIGA_HARNESS_PROXY_URL` or
  `http://127.0.0.1:8090`;
- if relying on auto-start, `giga doctor` reports `Proxy / Auto-start: ready`;
- `GPT2GIGA_API_KEY` or `GPT2GIGA_HARNESS_API_KEY` matches the proxy when API-key
  auth is enabled;
- `GIGACHAT_CREDENTIALS` is present for real upstream calls;
- the selected mode uses the intended explicit route: `/v1/chat/completions` or
  `/v2/chat/completions`;
- external CLI harnesses report `missing` until the matching executable is on
  `PATH` or configured in `~/.gpt2giga/harness/config.toml`; invalid configured
  paths and startup errors from broken CLI installations are reported by
  `giga harness inspect <id>` and the run result;
- real external CLI harness runs perform proxy preflight before launching the
  CLI, so proxy auto-start errors are reported directly instead of being buried
  in agent stdout/stderr.
- native history sync and import commands share the browser UI's native index;
  use `giga native sync --include-external --json` when debugging why a native
  ref is not visible in the UI.
- if a managed native session cannot be resumed, inspect the session bundle's
  `native_links` metadata for `resume_reason`.

## Current Limitations

The first MVP runs direct Chat Completions plus Codex, Claude Code, and Gemini
CLI command paths. External agent behavior still depends on each installed CLI's
current support for custom local API endpoints, non-interactive modes, native
resume, and local history formats. Use `--dry-run --json` first when validating
a new workstation, and treat external native history as metadata-only until
preview or import support for that connector is confirmed.

Attachment support is intentionally conservative. Document and binary transport
through external CLIs is path/reference based unless local CLI behavior has been
verified. Rich headless output uses persisted SSE events; native terminal output
continues to use its separate local polling transport. Harnesses or plugins that
do not emit structured deltas still appear atomically when their run completes.
