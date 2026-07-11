# gpt2giga-harness

Local agentic control plane for the `gpt2giga` compatibility gateway.

The distribution provides the `giga` and `gpt2giga-harness` commands and uses
the `gpt2giga_harness` Python namespace.

Install the first split release:

```sh
uv tool install "gpt2giga-harness==0.0.1"
giga doctor
giga ui
```

`gpt2giga-harness==0.0.1` depends on exactly `gpt2giga==0.2.2a1`. The gateway
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
