# Native CLI prefix examples

Install `gpt2giga-harness` and the provider CLI you intend to use. Harness does
not install or authenticate Codex CLI, Claude Code, or Gemini CLI.

Add only `giga` to a native command:

```sh
giga codex exec --json "inspect this repository"
giga claude -p "inspect this repository"
giga gemini -p "inspect this repository"
```

Machine-oriented examples remain native and can be composed normally:

```sh
printf 'summarize stdin' | giga claude -p -
giga codex exec --json "summarize" >codex-events.jsonl
CI=1 giga gemini --output-format stream-json -p "run checks"
giga codex resume --last
giga claude -c -p "continue"
giga gemini -r latest
```

For a human TTY, `giga codex`, `giga claude`, and `giga gemini` enter an
admitted structured Workbench route or visibly hand control to the provider.
Version drift disables only the structured L2 feature. Confirm the current
executable, version, L0/L1/L2 routes, fallback, and remediation without making
a provider request:

```sh
giga doctor --json
```

Provider-scoped metadata remains provider-owned:

```sh
giga codex --help
giga claude --version
giga gemini --help
```
