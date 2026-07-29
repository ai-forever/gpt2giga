# Installation

GigaLoom supports Python 3.10–3.14. Install at least one provider-native CLI
separately and complete that provider's own authentication flow.

## Install the preview

With `uv`:

```sh
uv tool install --prerelease allow 'gigaloom==0.5.1a1'
```

Or in an isolated Python environment:

```sh
python -m pip install --pre 'gigaloom==0.5.1a1'
```

Confirm the installed artifact:

```sh
giga --version
giga doctor
```

`doctor` reports capability and configuration status without reading prompt
content or contacting providers.

## Migrate from `gpt2giga-harness`

The PyPI project name changed before the first standalone target release.
Remove the historical distribution and install `gigaloom`; do not delete the
existing state directories:

```sh
uv tool uninstall gpt2giga-harness
uv tool install --prerelease allow 'gigaloom==0.5.1a1'
```

The Python namespace `gpt2giga_harness`, the `giga` and
`gpt2giga-harness` commands, `~/.gpt2giga/harness`, and `.giga/` remain
compatible. No dual-published shim is required.

## Optional gateway preset

The base package does not require gpt2giga. Install the optional extra only for
Direct Chat or the legacy local-gateway preset:

```sh
uv tool install --prerelease allow 'gigaloom[gpt2giga]==0.5.1a1'
```

This installs a pinned public gateway distribution. It does not require a
gateway repository, sibling checkout, editable dependency, or submodule. See
[Gateway integration](gateway-integration.md).

## Upgrade or remove

```sh
uv tool upgrade --prerelease allow gigaloom
uv tool uninstall gigaloom
```

Package removal does not delete user state under `~/.gpt2giga/harness`.
Back up or remove that state separately after reading
[Operations](operations.md).
