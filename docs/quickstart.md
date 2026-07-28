# Quickstart

Install GigaLoom first, then verify the local environment:

```sh
giga doctor
giga --version
```

Provider authentication stays provider-owned. Sign in with the native Codex,
Claude, or Gemini CLI before asking GigaLoom to launch it.

## Prefix a native command

GigaLoom adds one prefix and preserves the remaining native command:

```sh
giga codex exec --json "summarize this repository"
giga claude -p "summarize this repository"
giga gemini -p "summarize this repository"
```

Help, version output, stdin/stdout, JSON/JSONL, and exit status remain native.
If a CLI is missing or its contract has drifted, dispatch fails closed before
starting a provider session.

## Open the browser cockpit

```sh
giga ui
```

Open `http://127.0.0.1:8091/`. The default listener is loopback-only. In the
cockpit:

1. select or register a local project;
2. choose a provider adapter;
3. review the execution preview and required authority;
4. approve only the exact action you intend to run;
5. inspect the resulting events, diff, and evidence.

Use `giga tui` when a terminal-first workflow is preferable.

## Next steps

- [Harness reference](harness.md) for configuration and commands
- [Agents and multi-agent behavior](agents-and-multi-agent.md)
- [Operations](operations.md) for backup and troubleshooting
- [Security](security.md) for approval, redaction, and network boundaries
