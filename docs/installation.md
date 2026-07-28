# Installation

GigaLoom supports Python 3.10–3.14. Install at least one provider-native CLI
separately and complete that provider's own authentication flow.

## Install the preview

With `uv`:

```sh
uv tool install --prerelease allow 'gpt2giga-harness==0.5.1a1'
```

Or in an isolated Python environment:

```sh
python -m pip install --pre 'gpt2giga-harness==0.5.1a1'
```

Confirm the installed artifact:

```sh
giga --version
giga doctor
```

`doctor` reports capability and configuration status without reading prompt
content or contacting providers.

## Optional gateway preset

The base package does not require gpt2giga. Install the optional extra only for
Direct Chat or the legacy local-gateway preset:

```sh
uv tool install --prerelease allow 'gpt2giga-harness[gpt2giga]==0.5.1a1'
```

This installs a pinned public gateway distribution. It does not require a
gateway repository, sibling checkout, editable dependency, or submodule. See
[Gateway integration](gateway-integration.md).

## Upgrade or remove

```sh
uv tool upgrade --prerelease allow gpt2giga-harness
uv tool uninstall gpt2giga-harness
```

Package removal does not delete user state under `~/.gpt2giga/harness`.
Back up or remove that state separately after reading
[Operations](operations.md).
