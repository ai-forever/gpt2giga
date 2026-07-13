# Changelog

All notable changes to gpt2giga-harness are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.0.1] - 2026-07-13

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

### Changed
- **Package split**: the former branch-only `gpt2giga.harness` namespace was replaced by `gpt2giga_harness`; installing the gateway no longer adds Harness code or commands.
- **Gemini CLI integration**: Harness pins the selected GigaChat model through a trusted gateway contract and supports GigaChat v2 built-in tools.
- **Result rendering**: the UI shows execution plans, Codex plan events, tool progress, generated files, response sources, attachment render details, and compact session actions.

### Fixed
- **Worker lifecycle**: `giga ui` starts the worker reliably, and orphaned jobs no longer stop it prematurely.
- **Worktree safety**: tightened workspace boundaries and safe worktree handling for edit and apply flows.
- **Agent CLI attachments**: fixed Codex image and argument delivery, final response text extraction, and gateway preflight for external CLIs.
- **Generated files**: Direct Chat fetches and persists generated images with the correct proxy configuration.
- **Arena and UI state**: Arena state persists across navigation, native runs refresh after a response completes, and the initial native prompt and selected defaults are stored in session history.

---

[0.0.1]: https://github.com/ai-forever/gpt2giga/releases/tag/gpt2giga-harness-v0.0.1
