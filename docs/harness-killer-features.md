# Unified Harness Killer Features Architecture

This note maps the killer-features roadmap onto the code that already exists in
this branch. It is intentionally narrower than `docs/harness.md`: this document
is the integration map for the next product layer, while `docs/harness.md`
remains the user-facing runbook.

## Product Shape

Unified Harness should keep becoming a local Project Cockpit:

```bash
cd my-project
giga ui
```

The UI should open against the current repository, preserve project-scoped
history, route the same task through multiple harnesses, expose exactly what was
sent or executed, and keep edits inspectable before they are applied. It remains
a local control surface on top of `gpt2giga`; it does not replace the proxy.

## Stable Contracts

These entry points must stay stable while the killer features are added:

- `giga ui` opens the no-build browser cockpit.
- `giga chat` runs the direct chat harness through the proxy.
- `giga harness list`, `giga harness inspect`, and `giga harness run` expose
  built-in and plugin harnesses.
- `giga run --agent codex|claude|gemini` remains the backward-compatible agent
  alias surface.
- `giga init` and `giga project init` create non-secret project config.
- `giga session list` and `giga session show` inspect normalized session
  history.
- `giga native sync`, `giga native list`, and `giga native import` inspect and
  import native CLI history.
- UI model discovery stays bound to the selected explicit route:
  `/v1/models` for `v1`, `/v2/models` for `v2`.
- Normalized gpt2giga session history remains canonical. Native CLI stores are
  indexed, linked, imported, or resumed beside it; they are not the canonical
  database.

## Current Module Map

| Area | Current code |
| --- | --- |
| CLI entrypoint | `gpt2giga/harness/cli.py` |
| UI FastAPI app | `gpt2giga/harness/ui/app.py` |
| Static no-build UI | `gpt2giga/harness/ui/static.py` |
| Harness registry | `gpt2giga/harness/registry.py` |
| Harness contract | `gpt2giga/harness/types.py` |
| Built-in harnesses | `gpt2giga/harness/harnesses/` |
| Direct chat harness | `gpt2giga/harness/harnesses/direct_chat.py` |
| External CLI helpers | `gpt2giga/harness/harnesses/agent_cli.py` |
| Smart router | `gpt2giga/harness/routing.py` |
| Project identity/config | `gpt2giga/harness/project.py` |
| Workspace helpers | `gpt2giga/harness/workspace.py` |
| Session runner | `gpt2giga/harness/session_runner.py` |
| Session models/store | `gpt2giga/harness/sessions/` |
| Attachments | `gpt2giga/harness/attachments/` |
| Native session connectors | `gpt2giga/harness/native/codex.py`, `claude.py`, `gemini.py` |
| Native connector registry | `gpt2giga/harness/native/registry.py` |
| Native metadata index | `gpt2giga/harness/native/store.py` |
| Native process manager | `gpt2giga/harness/native/process.py` |
| Proxy discovery/sidecar | `gpt2giga/harness/proxy.py` |
| Harness docs | `docs/harness.md` |

## Already Implemented

The current branch already contains several foundations from the killer-features
roadmap.

### Unified Harness Foundation

- A built-in registry for `direct-chat`, `codex-cli`, `claude-code`,
  `gemini-cli`, and `echo`.
- Entry point discovery through the `gpt2giga.harnesses` Python entry point
  group.
- CLI commands for doctor, chat, UI, harness list/inspect/run, session
  list/show, project info/init, native sync/list/import, and harness scaffold.
- A direct-chat harness that uses the local proxy and can start a safe loopback
  proxy sidecar when configured and credentials are already present.
- Headless Codex CLI, Claude Code, and Gemini CLI harnesses with sanitized
  command/env dry-runs, proxy preflight, sidecar integration, and captured output
  redaction.

### Project Cockpit

- Project identity resolution in `resolve_project()`, preferring the git root
  when available and falling back to the current workspace.
- Stable project ids derived from the canonical project root path.
- Project metadata with root, display name, git branch, git dirty summary, config
  path, and per-project state directory.
- Safe project config in `.giga/harness.toml` with defaults, enabled harnesses,
  presets, and attachment limits.
- `giga init`, `giga project init`, `/api/project`, `/api/project/config`, and
  `/api/project/init`.
- Mutable per-project cockpit state in `projects/<project_id>/state.json` for
  the last selected harness, model, API mode, run mode, invocation mode, and
  selected session.
- Project-scoped sessions and native history filtering in the browser UI.

### Sessions And Run Inspection

- A normalized filesystem session store under `GPT2GIGA_HARNESS_DATA_DIR`.
- Session manifests plus append-only JSONL messages, runs, events, raw requests,
  raw responses, native links, and attachments.
- `HarnessSessionRunner` orchestration for create-and-run and run-in-session
  flows.
- Direct-chat multi-turn history through typed `HarnessChatMessage` context.
- Redaction before storing raw request/response data.
- UI inspector panels for run data, events, raw request, raw response, command,
  diff, attachments, storage, and native session/process data.
- Worktree-safe edit metadata under `run.metadata.workspace_execution`, with
  isolated worktree creation, changed/untracked file capture, patch storage,
  guarded apply, discard cleanup, and open-worktree path responses.

### Smart Router

- Deterministic, no-LLM recommendations from prompt text, requested mode,
  workspace presence, selected files, attachment kinds, harness capabilities,
  and harness availability.
- `/api/route/recommendation` returns a stable recommendation payload with
  `harness_id`, `mode`, `invocation_mode`, `confidence`, reasons, and warnings.
- The browser UI shows a Recommended badge, highlights the recommended harness,
  explains reasons/warnings, and can apply the recommended harness/mode/
  invocation in one click.
- Edit-looking prompts stay advisory unless `edit` mode is already selected
  explicitly.

### Attachments And Workspace References

- Attachment models, content-addressed project blob storage, session attachment
  logs, and a global attachment lookup index.
- Upload, paste, drag/drop, and workspace-file attachment flows in the no-build
  UI.
- Safe workspace tree and file metadata endpoints for `@file` references.
- Attachment limits, binary defaults, secret-looking filename checks, private-key
  payload rejection, path containment, gitignore respect, and deny-list checks.
- Per-harness attachment render plans for echo, direct-chat, Codex CLI, Claude
  Code, Gemini CLI, and custom harnesses.
- Harness integration so render-plan metadata reaches dry-runs, raw records, and
  commands/prompts where supported.

### Native Sessions

- Native capability metadata on `HarnessSpec`.
- Native session refs, links, transcript messages, managed/external statuses,
  and native command plans.
- Metadata-only native session index storage in `native/index.json`.
- Conservative Codex, Claude Code, and Gemini CLI discovery/import connectors.
- Managed native homes under `GPT2GIGA_HARNESS_DATA_DIR/native/`.
- UI and CLI native history sync/list/preview/import/link flows.
- Native process manager with PTY support on POSIX and pipe fallback elsewhere.
- Native process API and UI terminal panel using polling, stdin, stop, and
  redacted output persistence.
- Native start/resume links and native attachment rendering into command plans.

### Presets And Runbooks

- Project presets now support inline prompts, relative prompt files under the
  project root, invocation mode, workspace policy, selected-file defaults, and
  attachment-rule metadata.
- `giga init` writes starter prompt templates under `.giga/prompts/`.
- Preset templates can use project name, branch, selected files, last run diff,
  and user prompt variables without executing template code.
- `/api/project/presets` lists safe preset metadata and
  `/api/project/presets/{name}/render` returns the rendered run payload.
- `giga preset list` and `giga preset run <name>` expose the same contract from
  the CLI.
- The no-build UI renders preset chips that prefill the composer and run
  controls for review before execution.

### Tools And MCP Profiles

- Project config can define generic non-secret `[tools.<name>]` profiles with
  enabled state, title, kind, description, target harnesses, and safe config
  metadata.
- `gpt2giga/harness/tool_profiles.py` builds side-effect-free dry-run sync
  status for Codex CLI, Claude Code, and Gemini CLI managed config targets.
- `/api/tools` reports profile and per-harness status for the current project;
  `/api/tools/sync` returns redacted dry-run config previews without installing,
  authenticating, or writing external tool config.
- The browser UI exposes a Tools inspector tab with status chips and a
  `Dry-run sync` action.
- Secret-looking keys are rejected from project config and secret-looking values
  are redacted before API/UI output.

## Open Roadmap Status

The next work should not reimplement foundations that are already present. Use
this status to choose the next vertical slice.

| Roadmap slice | Status on this branch |
| --- | --- |
| Slice 00: architecture note | Covered by this document. |
| Slice 01: project-first cockpit | Implemented for project identity, config, mutable local state, project-scoped sessions, native history scoping, and UI header/default restoration. |
| Slice 02: `giga init` and `.giga/harness.toml` | Implemented for config, defaults, prompt template files, presets, and attachment settings. |
| Slice 03: live run event stream | Implemented as an MVP for headless UI runs: `/api/sessions/*/run/start` starts runs in the background, `/api/runs/{run_id}/events/stream` replays and streams persisted SSE events, and `/api/runs/{run_id}/cancel` requests cooperative cancellation. True stdout/message deltas still depend on individual harnesses emitting them. |
| Slice 04: native terminal pane | Implemented with native process manager, API, and UI terminal polling. SSE/WebSocket and resize can still be added later. |
| Slice 05: native session discovery/import | Implemented for Codex, Claude Code, and Gemini CLI with project scoping and UI/CLI flows. |
| Slice 06: attachment store | Implemented. |
| Slice 07: attachment API and composer UI | Implemented, except thumbnail generation and a separate thumbnail endpoint are still future work. |
| Slice 08: per-harness attachment rendering | Implemented. |
| Slice 09: worktree-safe edit/apply flow | Implemented as an MVP for headless external agent edit runs: `auto` policy creates an isolated git worktree, captures changed/untracked files and patch metadata, exposes diff/apply/discard/open-worktree endpoints, and wires Apply/Discard/Open controls into the Diff inspector. `temp_copy` remains a future fallback policy. |
| Slice 10: multi-harness arena | Implemented as an MVP: `/api/arena/runs` creates a JSON parent record under `arenas/<arena_id>.json`, runs selected headless harnesses sequentially with isolated request history, links child `HarnessRun` ids, aggregates child events through `/api/arena/runs/{arena_id}/events/stream`, and renders side-by-side UI result cards. Parallel execution and arena cancellation remain future work. |
| Slice 11: smart router | Implemented as an MVP: `gpt2giga/harness/routing.py` scores available harnesses deterministically from prompt text, attachments, workspace/selected files, requested mode, and harness capabilities; `/api/route/recommendation` exposes the result; the UI shows a Recommended badge with reasons/warnings and one-click apply. Edit-looking prompts remain non-edit unless `edit` was already selected explicitly. |
| Slice 12: presets and runbooks | Implemented as an MVP: presets support prompt templates, safe variables, workspace policy, API/CLI listing and rendering, CLI dry-run execution, and UI preset chips that prefill run controls. Multi-step runbook orchestration remains future work. |
| Slice 13: tools/MCP profiles | Implemented as an MVP: `.giga/harness.toml` supports non-secret `[tools.<name>]` profiles; `/api/tools` and `/api/tools/sync` expose per-harness status plus redacted dry-run config previews; the UI has a Tools inspector tab. Actual external tool install/auth/config writes remain future work. |
| Slice 14: issue/PR mode | Implemented as an MVP: every completed run stores `run.metadata.pr_artifact` with deterministic PR title/body/patch/changed-file data, `/api/runs/{run_id}/pr`, `/api/runs/{run_id}/patch`, and `/api/runs/{run_id}/branch` expose local artifact workflows, `giga run pr-summary|patch <run_id>` exports them from the CLI, and the UI has a PR inspector tab with copy actions plus guarded local branch creation. Hosted GitHub/GitLab writes remain future work. |
| Slice 15: project memory and decision log | Open. |
| Slice 16: provenance and replay | Partially implemented through stored runs, commands, raw records, attachments, events, and native links. Replay/fork behavior remains open. |
| Slice 17: secrets firewall and context budget inspector | Partially implemented through redaction and attachment safety checks. Pre-run scanner and budget inspector remain open. |
| Slice 18: local evals/benchmarks | Open. |
| Slice 19: plugin/marketplace-ready harness format | Partially implemented through entry point loading and scaffold output. Metadata schema, validation, and UI config forms remain open. |
| Slice 20: editor bridge | Open. |

## Target Data Boundaries

Project and session state should remain transparent JSON/JSONL:

```text
~/.gpt2giga/harness/
  sessions/<year>/<month>/<session_id>/
    session.json
    messages.jsonl
    runs.jsonl
    events.jsonl
    raw_requests.jsonl
    raw_responses.jsonl
    native_links.jsonl
    attachments.jsonl
  projects/<project_id>/
    state.json
    attachments/<sha256>/original
    attachments/<sha256>/metadata.json
  arenas/<arena_id>.json
  worktrees/<session_id>/<run_id>/
  native/
    index.json
    codex/homes/<project_id>/
    claude/homes/<project_id>/
    gemini/homes/<project_id>/
```

Future slices should keep adding inspectable records instead of hiding state in
opaque stores.

## Next Recommended Slice

The highest-value next implementation slice is Slice 15 for project memory and
decision log: persist explicit project knowledge, expose CRUD in the UI/CLI, and
inject only enabled memory into run metadata with visible provenance.

Slice 03 can still be enriched later with richer per-harness stdout/message
delta emission, Slice 10 can grow parallel execution and arena cancellation,
Slice 12 can later grow into multi-step runbook orchestration, Slice 13 can
later add real opt-in tool config writes after an explicit safety review, and
Slice 14 can later add hosted issue/PR integrations behind explicit user action.

## Safety Rules

- Do not store or print upstream credentials, OAuth tokens, certificates,
  cookies, `.env` contents, private keys, or local proxy API keys.
- Native discovery must not mutate the user's real native tool config.
- Managed native homes may be written only under `GPT2GIGA_HARNESS_DATA_DIR`.
- Attachment APIs should return public metadata and stable ids, not blob storage
  paths.
- External agent commands should keep using shared env construction and output
  redaction helpers.
- UI routes that can execute local commands should remain loopback-only unless
  the user explicitly opts into remote binding.
