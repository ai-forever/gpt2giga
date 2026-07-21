# Changelog

All notable changes to gpt2giga-harness are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.3.0a1] - 2026-07-20

### Added
- **Provider-native CLI completion**: root help now teaches the literal `giga codex|claude|gemini` prefix contract, `giga completion` emits conservative Bash/Zsh/Fish/PowerShell completion without parsing provider suffixes, and doctor reports executable/version plus L0/L1/L2 transport degradation and remediation.
- **Provider-neutral providers and routes**: added user profiles for OpenAI-, Anthropic-, and Gemini-compatible APIs, per-route model defaults, reference-only authentication, bounded health/model discovery, and an optional `gpt2giga` preset instead of a mandatory Harness-to-gateway coupling.
- **Safe provider migration**: legacy defaults can be converted only after a deterministic dry run and a verified pre-upgrade backup; migration revalidates source state under a lock, retains a journal, and permits rollback only by restoring the original archive.
- **Skills, Plugins, and MCP library**: added an offline-first catalog, portable Skills, a first-party starter pack, Codex/Claude/Gemini MCP targets, Codex/Claude Plugins, Gemini extensions, and a preview SDK for external adapter/integration packages.
- **Federated integration discovery**: metadata from `skills.sh` and NeuralDeep can be imported as an immutable Skill or exact MCP plan; catalog presence, popularity, and correlation never grant install authority or replace the official source pin/integrity.
- **Target-scoped installation lifecycle**: single-target and all-Harness flows bind preview and approval to exact package/artifact hashes, scope, permissions, and target ownership, then provide verification, update, compensation, recovery, and rollback with safe `managed_home` scope by default.
- **Generated documents in Cockpit**: saved files can be downloaded through a bounded SDK endpoint, while self-contained HTML with scripts can open in a sandboxed preview without forms, external-network, or same-origin authority.

### Changed
- **Integrations as a Plugin Library**: Cockpit unifies built-in and external Skills/MCP with separate source filters, target-aware status, and explicit Add/preview/apply actions; Settings manages providers, routes, and models through backend-authoritative read-back.
- **Provider-neutral base package**: base `gpt2giga-harness` no longer installs the gateway and GigaChat SDK implicitly; integration with the current gateway remains the exact optional extra `gpt2giga==0.2.4a1`.

### Fixed
- **Workbench and messages**: fixed generated-file downloads, full-response Copy/Edit actions, document scrolling, the resizable composer, and desktop/mobile shell layout.
- **Plugin lifecycle**: connection state is reset after disconnect/reload, and large library loading uses bounded projections without redundant repeated work.

## [0.2.0a1] - 2026-07-18

### Added
- **Provider-neutral execution contracts**: added strict content-free provider/route references, execution-boundary-only `SecretRef` resolution, immutable execution snapshots, versioned structured session links, and a bounded JSON-RPC supervisor with generation isolation, backpressure, and an approval bridge.
- **Native structured providers**: Codex app-server, Gemini ACP, and Claude provider handoff now have testable lifecycle contracts; durable runs, workflows, schedules, Arena, and Eval can use structured native transports without merging provider-owned and Harness-owned state.
- **Adapter SDK conformance kit**: external adapter packages can validate entry points, metadata, capabilities, redaction, and offline lifecycle behavior before installation into Harness.
- **Message actions**: Copy fetches and copies the complete retained assistant response even when the read model displays a bounded preview; the pencil action loads the complete user prompt into the composer for editing and rerunning.
- **CLI version**: `giga --version` and `gpt2giga-harness --version` print the installed distribution version.

### Changed
- **Structured Workbench by default**: supported coding harnesses now prefer `native_structured` execution while keeping explicit one-shot and native-terminal choices where available.
- **Clean source distribution**: the PyPI sdist no longer contains TypeScript sources, frontend tests, Vite/ESLint configuration, or the npm lockfile; deterministically built content-addressed Cockpit assets remain in both sdist and wheel.
- **Compact Cockpit assets**: duplicate `.br`/`.gz` files are no longer stored in the repository or wheel; integrity-bound identity assets are gzip-compressed in memory when served locally.

### Fixed
- **Live Codex subagent events**: the fallback rollout is tailed during an active turn, so calls and nested tool activity appear immediately instead of only after completion or cancellation.
- **Fast version output**: the console entry point handles `giga --version` before importing FastAPI, providers, UI, and runtime modules.
- **Cockpit layout**: the Workbench label is centered in the narrow primary rail, while Codex subagent result disclosures and long details no longer shift or clip under focus and wrapping.
- **Read-model and UI lifecycle**: session read-index initialization is serialized, and the embedded UI worker cold-start timeout now allows realistic startup latency.

## [0.1.0b1] - 2026-07-17

### Changed
- **Native Automation**: Cockpit now creates and edits agents, workflows, and schedules through typed backend APIs, preserving optimistic revision checks and explicit operator actions instead of requiring copied YAML commands.
- **Simultaneous Arena**: multi-harness comparison is rebuilt as independent chats with parallel startup, separate history, and per-participant follow-ups.
- **Message rendering**: Cockpit now uses a standard Markdown pipeline with safe HTML, syntax highlighting, tables, task lists, and locally packaged KaTeX.
- **Cockpit model settings**: default chat and session-title models can now be selected independently from the discovery list and persist in backend-owned Harness Settings; Workbench and headless runs consume the stored choices without a model ID hardcoded in the client or session runner.
- **Cockpit V2 rollout**: the packaged React cockpit is now the default local UI, prior top-level deep links redirect to their canonical Workbench, Runs, Automation, Evaluation, or Integrations destinations, and `/legacy/**` remains available as a release-level rollback path without retained-state migration. New Cockpit streams start at the durable live tail while bounded snapshots own retained history, so opening a large completed run does not replay every stored event through the browser. Read-model ETags receive a fresh process namespace so a restart, data-dir switch, or rollback cannot reuse a stale browser snapshot with the same SQLite generation.

### Fixed
- **Codex continuity**: app-server resume preserves conversation history and subagent activity, including `output_text` from earlier turns, while Workbench displays the related events without flattening their structure.
- **UI lifecycle**: selected-route readiness survives durable retries, the UI worker pool is explicitly configurable, and graceful shutdown is time-bounded.

### Added
- **Base-install dependency policy**: clean wheel installs now run a versioned audit over the ten reviewed direct dependencies, a 64-distribution resolved ceiling, and explicit Office, remote-channel, external-client, and sandbox-provider exclusion families; optional providers remain separately installed integrations instead of hidden base dependencies.
- **CI and support doctor contract**: `giga doctor --json` now includes stable report identity plus package, Python, platform, and existing external-CLI compatibility evidence; `--fail-on blocked|degraded` provides an explicit CI exit policy, while `--output` atomically writes a canonical redaction-safe mode-`0600` issue attachment.
- **External CLI support windows**: version-aware probes now require both proven capabilities and the declared Codex CLI `0.144.x`, Claude Code `2.1.x`, or Gemini CLI `0.46.x` minor line; versions that are too old or lose required flags become `unsupported`, while newer or unparseable versions report machine-readable `degraded` and remain fail-closed until fixtures and the support window are updated.
- **Offline state restore and compatibility gate**: `giga state restore` now verifies and stages a private backup before an explicit atomic replacement, rejects active or concurrently changing destinations, preserves file modes and SQLite integrity, accepts older runtime schemas for forward migration on next open, and fails closed on schemas newer than the installed Harness. Package rollback restores a pre-upgrade archive instead of attempting a reverse migration.
- **Deterministic user-state backup**: `giga state backup` now creates an atomic, versioned, content-addressed archive of a quiescent Harness data directory with consistent SQLite snapshots, transient-file and symlink protections, and mode `0600`; `giga state verify` checks manifest hashes, safe paths, ZIP integrity, and every retained SQLite database before an upgrade or rollback.
- **Remaining Cockpit V2 surfaces**: Automation now groups Agents, Workflows, and Schedules; Evaluation groups Arena, Evals, and Baselines; and Integrations groups Harnesses, Models & routes, MCP, and selected-plan Doctor. Secondary tabs and selected rows are deep-linkable, React immediately reduces responses to bounded content-free projections, and run/eval/baseline/probe/doctor operations remain separate actions on the existing APIs while legacy routes stay available.
- **Cockpit Workbench and Runs verticals**: the opt-in React client now implements the canonical Work → Run → Evidence → Review → Reuse path over bounded session/run projections and durable live tails, exposes real ownership, trace, artifact, approval, Attention, apply, and promotion state, and keeps approval, apply, and promotion as separate explicit operations with responsive Workbench panel controls.
- **Event-driven Cockpit streams**: run events now use per-run notifications, durable opaque cursors, and `Last-Event-ID` instead of 250 ms full-state polling; heartbeats pick up cross-process writes, bounded client queues require an explicit resnapshot under backpressure, and the React stream store batches presentation deltas per animation frame, prioritizes control events, and provides bounded virtualization, scroll-anchor, and incremental Markdown primitives.
- **Bounded Cockpit read model**: additive indexed session/run lookups, byte- and cursor-bounded message/run/event/artifact pages, ETag-bound snapshots, and lazy raw/diff/report projections replace full-bundle Cockpit V2 startup reads; the client cancels stale scopes, de-duplicates concurrent requests, isolates out-of-order responses, and updates targeted cache entries.
- **Asynchronous UI data plane**: all FastAPI routes now carry exhaustive workload, storage/execution owner, deadline, cancellation, idempotency, payload, cursor, and latency contracts; filesystem, SQLite, network, subprocess, durable-job, and SSE work uses workload-bounded offload, while content-free diagnostics expose event-loop lag, queue/DB/storage/handler/serialization timing, response bytes, and cancellation counts.
- **Packaged Cockpit V2 shell**: added a pinned React/TypeScript/Vite frontend with five route-split product surfaces, lazy inspector boundaries, a deterministic content-hashed manifest, integrity-bound Brotli/gzip assets, CSP-safe same-origin loading, and Node-free wheel smoke coverage; the legacy cockpit remains an explicit recovery route.

- **Mutation policy conformance**: all unsafe-method Harness API routes now have one fail-closed semantic inventory covering effect class, enforcement control and owner, stable permission actions where applicable, and retained allow/ask/deny/stale/redaction evidence; app construction and CI reject unclassified routes.
- **Cockpit performance budgets**: the packaged shell now publishes and enforces machine-readable budgets for critical asset weight, first-ready timing, large trace DOM size/rendering, cursor reconnect, and bounded diff/report previews; full retained report, copy, open, and apply actions remain explicit.
- **Selected-run readiness**: CLI/API/UI preflight now reports redaction-safe `ready`/`degraded`/`blocked` checks and remediation before spawn only for the selected harness, invocation mode, route/model, workspace policy, and durable/synchronous path; unrelated failures do not block local Echo.

## [0.0.1a3] - 2026-07-15

### Added
- **Review-to-reuse onboarding**: the Work rail now guides an eligible successful run to its exact provenance/promotion inspector, while promotion preview/apply and scheduling remain separate explicit operator actions.
- **Evidence-to-review onboarding**: the Work rail now continues from terminal evidence to the exact retained worktree Diff when an isolated patch exists, while apply and approval remain separate explicit operator actions.
- **Run-to-evidence onboarding**: Work now reveals a compact Run → Evidence path after the first run starts and enables a deep link to that exact retained Runs Center trace only after terminal completion.
- **Cross-harness review team**: a reviewed example now fans out read-only explorer, security, tests, and maintainability roles across Codex, Claude, and Gemini, preserves per-child durable evidence through partial failure, and synthesizes cited artifacts without a shared writable workspace.
- **Nightly compatibility guardian**: a reviewed example now packages a pinned Codex/Claude/Gemini eval, exact adapter-dimension baselines, read-only regression triage, and a durable nightly schedule that runs without the UI.
- **Reviewed-patch example**: a disposable issue fixture now packages reviewed planner, isolated implementer, and read-only reviewer profiles with a durable workflow and post-apply eval; source mutation, apply, commit, push, and hosted writes remain explicit operator decisions.
- **Offline first-run demo**: a disposable fictional inventory repository now verifies `giga init`, redaction-safe diagnostics, a local Echo read run, and the generated smoke eval while keeping runtime state inside the copied demo and requiring no credentials, proxy, external agent CLI, or public network.
- **First-run doctor**: `giga doctor [workspace] --json` now emits a redaction-safe readiness report for the proxy, routes, models, adapter CLI versions, workspace and Git state, durable worker, managed homes, and MCP snapshots, with actionable remediation commands and read-only runtime inspection.
- **Capability matrix**: `giga harness capabilities` generates reviewable Markdown and JSON views directly from the built-in CLI adapters' runtime parity contracts.
- **Idempotent side-effect evidence**: the durable runtime can atomically reserve opaque Harness-owned side-effect tokens and retain immutable redacted completion evidence without making arbitrary edit attempts retry-safe.
- **Bounded side-effect executor**: Harness-owned runtime events now bind token reservation, durable outbox delivery, and immutable completion evidence in one transaction; duplicate delivery reuses completed evidence while ambiguous reservations remain blocked.
- **Durable recovery marker**: an opt-in durable job can hash a supplied opaque side-effect token before persistence and record one fixed Harness-owned marker through the atomic executor; owner-loss retries reuse completed evidence while ambiguous reservations fail closed.
- **Policy audit evidence**: reviewed promotion now retains an append-only, hash-chained record of policy resolution, user decision, exact enforcement owner, approval grant, and source/patch binding; audit rows reject update and deletion.
- **Reviewed evidence lineage**: successful reviewed operations now expose a validated, content-addressed evidence manifest through runtime export, run provenance, replay requests, and run-to-agent/workflow/eval promotion without exposing raw approval bindings or captured content.
- **GigaChat compatibility evidence**: completed headless Codex, Claude, and Gemini runs now expose content-addressed provenance for the observed `gpt2giga` route, requested model/API mode, and normalized stream, tool, usage, error, and cancellation semantics without retaining prompt or response content.

### Fixed
- **Scheduled eval attention**: after an exact schedule hash passes `test-now`, a later failed eval now pauses the schedule and creates one retained Attention item with the scorecard summary.
- **Durable scheduled evals**: duplicate delivery of one schedule occurrence now reuses the original target run instead of creating a second eval/job, and worker-triggered scorecards are retained under the resolved Harness project state directory.
- **Reviewed promotion**: `git.apply` approval is now bound once to the exact source commit, captured patch SHA-256, and branch intent; stale source, changed patch, and approval rebinding fail closed before the checkout is modified.

## [0.0.1a2] - 2026-07-14

### Added
- **Safe native CLI startup**: starting or resuming Codex, Claude, and Gemini now checks executable capabilities, the workspace, proxy route, and process-spawn policy; actions that require trust receive explicit confirmation.
- **Durable native terminals**: PTY process state and ownership are persisted in the coordination store with crash reconciliation and bounded process-group termination; terminals support SSE replay through `Last-Event-ID`, cursor-polling fallback, and browser-driven PTY resize.
- **Interactive message queue**: an active Harness run can be interrupted, while subsequent turns can be placed in a durable queue and shown beside the composer until they are submitted in order.
- **Attachment transports**: adapters declare support and delivery methods for individual attachment kinds; Harness builds an inspectable render plan for prompt references, CLI flags, staged paths, and metadata-only inputs.
- **Compatibility evidence**: added version-aware Codex, Claude, and Gemini CLI probes, adapter parity contracts, live compatibility telemetry, and Eval Lab matrices based on structured capability events.

### Changed
- **Headless adapter profiles**: model, reasoning effort, permission/workspace policy, budgets, and allowed/disallowed tools are now applied as a capability-checked immutable snapshot; trusted managed MCP profiles are materialized into isolated CLI homes without changing the user's native configuration.
- **External CLI session continuity**: Codex uses supervised app-server threads for multi-turn headless continuity with interrupt support; Harness persists opaque runtime links and explicitly reports continuation limits for adapters without a safe resume contract.
- **Release contract**: Harness now pins `gpt2giga==0.2.3a2`, and `gpt2giga-harness` publishing uses PyPI Trusted Publishing.
- **Documentation**: added dedicated Russian and English documentation for the architecture, security boundaries, headless/native execution flows, and the complete control-plane API.

### Fixed
- **Native session continuity**: resume snapshots now preserve the model, API route, permission mode, and workspace; discovery and reconciliation restore Codex, Claude, and Gemini history without modifying vendor-owned homes or duplicating turns.
- **Gemini CLI**: fixed initial prompt delivery, selected-model pinning, live-reply synchronization, startup/runtime error presentation, and multi-turn native conversation stability.
- **Claude Code**: fixed startup with managed MCP configuration and selected GigaChat model pinning for headless and native requests.
- **Tool activity**: native streams now present Claude and Gemini tool calls/results, including Claude subagent activity, without mixing them into normal assistant text.

## [0.0.1a1] - 2026-07-13

The first standalone alpha release of the local agentic control plane. APIs,
stored-state formats, and automation contracts in the `0.0.x` line are not yet
considered stable.

### Added
- **Standalone distribution and CLI**: added the `gpt2giga-harness` package with the `gpt2giga_harness` Python namespace, `giga` and `gpt2giga-harness` commands, the `gpt2giga.harnesses` plugin entry-point group, and an exact dependency on `gpt2giga==0.2.3a1`.
- **Project Cockpit**: added a local FastAPI UI with packaged no-build assets, project-aware navigation, session history, an inspector, live events, a terminal, and automatic durable worker startup.
- **Built-in Harness adapters**: added Direct Chat, Codex CLI, Claude Code, Gemini CLI, and Echo with shared contract metadata, availability checks, model/API mode selection, and safe gateway sidecar startup.
- **Native sessions**: added discovery, indexing, and import of existing Codex, Claude, and Gemini sessions, plus managed native processes, terminal streaming, attachments, project scoping, and interactive workspace trust confirmation.
- **Projects and context**: added `.giga/` project configuration, session scoping, workspace references, attachments, local file and image preview, project memory, run presets, reusable agent profiles, and configurable executable paths in `~/.gpt2giga/harness/config.toml`.
- **Safe edit flows**: added isolated worktrees, lease and policy checks, preview and approval before applying changes, editor and terminal bridges, and PR-ready artifacts.
- **Durable runtime**: added a SQLite coordination store, worker leases, retries, cancellation, crash reconciliation, run provenance, replay, and recovery of unfinished jobs.
- **Orchestration**: added versioned workflows, reusable agents, agent teams and handoffs, promotion of successful runs, schedules, and an automation center.
- **Harness selection and comparison**: added the deterministic Smart Router, a multi-Harness Arena with dedicated workspaces, and a compatibility Eval Lab with local result matrices.
- **Tools, MCP, and policy**: added shared tool and secret contracts, MCP profile discovery and dry-run synchronization, managed MCP configuration, preflight diagnostics, and approval-gated actions.
- **Diagnostics and documentation**: added `giga doctor`, inspect/config/session/native commands, an alpha quickstart, a migration guide, and documented first-release limitations.

---

[0.3.0a1]: https://github.com/ai-forever/gpt2giga/compare/gpt2giga-harness-v0.2.0a1...gpt2giga-harness-v0.3.0a1
[0.2.0a1]: https://github.com/ai-forever/gpt2giga/compare/gpt2giga-harness-v0.1.0b1...gpt2giga-harness-v0.2.0a1
[0.1.0b1]: https://github.com/ai-forever/gpt2giga/compare/gpt2giga-harness-v0.0.1a3...gpt2giga-harness-v0.1.0b1
[0.0.1a3]: https://github.com/ai-forever/gpt2giga/compare/gpt2giga-harness-v0.0.1a2...gpt2giga-harness-v0.0.1a3
[0.0.1a2]: https://github.com/ai-forever/gpt2giga/compare/gpt2giga-harness-v0.0.1a1...gpt2giga-harness-v0.0.1a2
[0.0.1a1]: https://github.com/ai-forever/gpt2giga/releases/tag/gpt2giga-harness-v0.0.1a1
