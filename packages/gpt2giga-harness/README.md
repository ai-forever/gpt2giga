# gpt2giga-harness

Local agentic control plane for the `gpt2giga` compatibility gateway.

The distribution provides the `giga` and `gpt2giga-harness` commands and uses
the `gpt2giga_harness` Python namespace.

Release notes: [Russian](./CHANGELOG.md) · [English](./CHANGELOG_en.md).

Install the first split release:

```sh
uv tool install "gpt2giga-harness==0.0.1"
giga doctor
giga ui
```

`giga ui` starts a local durable worker automatically when needed. Pass
`--no-start-worker` to keep worker lifecycle under separate supervision.

Codex, Claude Code, and Gemini are discovered on `PATH` by default. Override a
non-standard installation in the user-owned
`~/.gpt2giga/harness/config.toml`:

```toml
[executables]
"codex-cli" = "/custom/bin/codex"
"claude-code" = "/custom/bin/claude"
"gemini-cli" = "C:\\Users\\me\\bin\\gemini.cmd"
```

Use `giga config path`, `giga config set executables.codex-cli /custom/bin/codex`,
and `giga harness inspect codex-cli --json` to manage and diagnose resolution.
Configured executable paths take precedence over `PATH` and must be absolute.

`gpt2giga-harness==0.0.1` depends on exactly `gpt2giga==0.2.3a1`. The gateway
can be started separately with `gpt2giga`; Harness can also start a temporary
local sidecar for supported direct runs.

Plugins keep using the `gpt2giga.harnesses` entry-point group, while their
imports and entry-point targets use `gpt2giga_harness.*`:

```toml
[project.entry-points."gpt2giga.harnesses"]
my-harness = "my_package.my_harness:MyHarness"
```

When upgrading from the old combined prerelease, uninstall both distributions
before reinstalling this package. Existing `~/.gpt2giga/harness` and `.giga/`
state stays in place and must not be deleted during the package migration.
