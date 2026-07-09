# Unified Harness

Unified Harness is a local control surface on top of `gpt2giga`. It lets you
choose a harness, choose a GigaChat model, choose the explicit GigaChat Chat
Completions backend mode (`/v1` or `/v2`), and run quick smoke tests from either
the CLI or a small browser UI.

It does not replace the existing `gpt2giga` proxy entry point. You can still
start the proxy yourself as before, then use `giga` or `gpt2giga-harness` as the
local harness client. For local `127.0.0.1` proxy URLs, the direct-chat harness
can also start a temporary `gpt2giga` sidecar when the proxy is down and real
GigaChat credentials are already present in the environment.

## Quickstart

Start the proxy:

```bash
uv run gpt2giga
```

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

Open the local UI:

```bash
giga ui
```

From a project directory, inspect or initialize the project cockpit config:

```bash
giga project info
giga project init
# Short alias:
giga init
```

By default the UI binds to `127.0.0.1:8091`. To bind remotely you must opt in:

```bash
giga ui --host 0.0.0.0 --allow-remote
```

Remote binding can expose local harness execution. Use it only behind a trusted
network boundary.

## Configuration

CLI flags override environment variables. Useful variables:

```bash
GPT2GIGA_HARNESS_PROXY_URL=http://127.0.0.1:8090
GPT2GIGA_HARNESS_API_KEY=<local-proxy-api-key>
GPT2GIGA_HARNESS_DEFAULT_MODEL=GigaChat-2-Max
GPT2GIGA_HARNESS_DEFAULT_API_MODE=v2
GPT2GIGA_HARNESS_UI_HOST=127.0.0.1
GPT2GIGA_HARNESS_UI_PORT=8091
GPT2GIGA_HARNESS_AUTO_START_PROXY=True
GPT2GIGA_HARNESS_PROXY_START_TIMEOUT_SECONDS=15
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

Project init also creates safe prompt templates under `.giga/prompts/`.
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

Tool profiles are dry-run only in this milestone. The harness parses them,
reports per-harness status in the UI Tools tab, and generates redacted config
previews through:

```text
GET  /api/tools
POST /api/tools/sync
```

No external tools are installed, authenticated, or written into Codex, Claude,
or Gemini config files. Profile names are constrained to safe identifier
characters, secret-looking keys are rejected while loading project config, and
secret-looking values are redacted in API/UI output.

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

## Built-in Harnesses

| Harness | Status | Purpose |
|---|---|---|
| `direct-chat` | MVP | Sends OpenAI-style Chat Completions to `/v1/chat/completions` or `/v2/chat/completions`. |
| `echo` | MVP | Local no-network smoke harness for tests and UI checks. |
| `codex-cli` | MVP | Builds and runs a sanitized `codex exec` command against the local proxy. |
| `claude-code` | MVP | Builds and runs sanitized Claude Code print-mode commands against the local proxy. |
| `gemini-cli` | MVP | Builds and runs sanitized Gemini CLI headless commands against the local proxy. |

Inspect one harness:

```bash
giga harness inspect direct-chat
```

Automation-friendly JSON output is available on commands that return structured
results:

```bash
giga harness list --json
giga harness run echo --prompt "hello" --json
```

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

`giga ui` serves the local Harness Control Panel as one no-build HTML page. It
binds to `127.0.0.1:8091` by default. Remote binding is rejected unless you pass
`--allow-remote`.

The UI is populated from `HarnessRegistry`, so built-in and entry-point
harnesses appear in the browser without frontend code changes. It shows each
harness' availability status, kind, capabilities, tags, and missing/error
details when discovery fails.

The UI is a chat-like harness cockpit with:

- persistent session sidebar with search, workspace and harness filters, pin,
  archive, and delete controls;
- harness selection;
- model input with proxy-backed model suggestions when available;
- explicit API mode selection: `v1` maps to `/v1/chat/completions`, and `v2`
  maps to `/v2/chat/completions`;
- capability, mode, and workspace execution policy selection;
- optional workspace path for harnesses that declare workspace support;
- dry-run and stream toggles where the selected harness supports them;
- prompt input;
- file and image attachments in the composer;
- `@file` workspace references from the current project;
- smart router recommendation badge with reasons and one-click apply;
- user, assistant, and error messages in the selected session;
- multi-harness arena comparison for running the same prompt against several
  headless harnesses;
- run, arena, events, raw request, raw response, command, diff, PR,
  provenance, attachments, and storage inspector panels;
- copy buttons for the equivalent CLI command and direct-chat curl command.

Echo runs entirely locally and does not require credentials. Direct-chat sends
requests through the configured local proxy or auto-started local sidecar and
therefore needs real GigaChat credentials for live upstream responses. External
agent CLI harnesses such as Codex, Claude Code, and Gemini can be previewed with
dry-run even when their executable is missing.

Session history survives browser refreshes and UI restarts. New runs are stored
in the selected session, and `direct-chat` receives previous user and assistant
messages from that session as multi-turn context.

The stream checkbox starts a background headless run, subscribes to
`/api/runs/{run_id}/events/stream` with SSE, and appends persisted run events to
the Events inspector while the run is active. The Cancel button calls
`/api/runs/{run_id}/cancel`; harnesses that observe the in-memory cancel token
can stop cooperatively, while older blocking subprocess paths may continue until
the subprocess returns.

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

- `auto`: use an isolated worktree for external agent `edit` runs in git
  repositories, otherwise use the current workspace;
- `current`: run in the selected workspace;
- `worktree`: request an isolated git worktree and fall back with a recorded
  warning when the workspace is not a git repository;
- `temp_copy`: reserved for a future non-git copy policy; current MVP records a
  fallback to the current workspace.

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

`apply` is intentionally guarded: it refuses to patch the source checkout when
the checkout has local changes or no longer points at the run's base commit.
The optional branch field creates a new branch before applying when the target
checkout is clean and still at the base commit. `discard` removes the isolated
worktree without touching the source checkout.

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
rendered reference such as `@gpt2giga/harness/workspace.py`, not a copied
repository file.

The selected harness determines the render plan:

| Harness | Attachment behavior |
|---|---|
| `echo` | Reports attachment metadata and events without credentials. |
| `direct-chat` | Uses OpenAI-style image content parts for stored images and inlines small text files with truncation warnings. Workspace files are referenced by path. |
| `codex-cli` | Adds safe path or `@file` references to the prompt. Image CLI flags are not enabled unless support is verified. |
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
  --prompt "Inspect @gpt2giga/harness/workspace.py" \
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
  and Attachments for path-reference behavior.

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
```

Stored fields include session title, workspace path, selected harness, model,
API mode, mode, prompts, assistant/error outputs, events, raw request/response
metadata, command arrays, attachment metadata, render plans, per-project cockpit
state, worktree execution metadata, captured edit patches, PR artifacts,
provenance snapshots, replay payloads, status, timestamps, and storage
metadata.

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
- [ ] A streamed headless run appends Events inspector rows before completion.
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

1. Create `gpt2giga/harness/harnesses/my_harness.py`.
2. Subclass `BaseHarness`.
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
   giga ui
   ```

For a starting template:

```bash
giga harness scaffold my-harness
```

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
  `PATH`; startup errors from broken CLI installations are reported by the run
  result;
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
verified. SSE/WebSocket streaming for live attachment run events remains future
work; native terminal transport will be local-only when enabled.
