# Changelog

All notable changes to gpt2giga-harness are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.0.1a3] - Unreleased

### Added
- **Capability matrix**: `giga harness capabilities` generates reviewable Markdown and JSON views directly from the built-in CLI adapters' runtime parity contracts.
- **Idempotent side-effect evidence**: the durable runtime can atomically reserve opaque Harness-owned side-effect tokens and retain immutable redacted completion evidence without making arbitrary edit attempts retry-safe.

### Fixed
- **Durable scheduled evals**: duplicate delivery of one schedule occurrence now reuses the original target run instead of creating a second eval/job, and worker-triggered scorecards are retained under the resolved Harness project state directory.

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

[0.0.1a3]: https://github.com/ai-forever/gpt2giga/compare/gpt2giga-harness-v0.0.1a2...HEAD
[0.0.1a2]: https://github.com/ai-forever/gpt2giga/compare/gpt2giga-harness-v0.0.1a1...gpt2giga-harness-v0.0.1a2
[0.0.1a1]: https://github.com/ai-forever/gpt2giga/releases/tag/gpt2giga-harness-v0.0.1a1
