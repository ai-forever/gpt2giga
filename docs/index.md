# GigaLoom documentation

GigaLoom is a local, provider-neutral control plane for coding agents. Use its
CLI, terminal UI, or browser cockpit to run native agents while keeping
worktrees, approvals, evidence, schedules, and stored state under explicit
local policy.

The current `0.5.1a1` line is an alpha preview. Begin with
[Installation](installation.md), then complete the [Quickstart](quickstart.md).

## Choose a path

| Goal | Guide |
|---|---|
| Install or upgrade the preview | [Installation](installation.md) |
| Run the first governed session | [Quickstart](quickstart.md) |
| Understand components and trust boundaries | [Architecture](architecture.md) |
| Back up state or troubleshoot a local runtime | [Operations](operations.md) |
| Review privacy and authority boundaries | [Security](security.md) |
| Connect the optional gpt2giga gateway | [Gateway integration](gateway-integration.md) |
| Contribute or prepare a release | [Contributing](contributing.md) · [Release](release.md) |

The detailed [Harness reference](harness.md), [agent workflows](agents-and-multi-agent.md),
and [capability matrix](agent-capability-matrix.md) cover the wider product
surface.

## Core boundary

The base distribution is standalone. It does not import or require a
`gpt2giga` source checkout. Provider CLIs own their authentication, while
GigaLoom owns local orchestration, approval, redaction, and evidence.

Gateway compatibility is an optional installed-artifact integration. The
gateway's normalized protocol and public API compatibility remain separate
contracts, linked from [Gateway integration](gateway-integration.md).

## Project locations

- [Source, issues, and releases](https://github.com/krakenalt/gigaloom)
- [Published documentation](https://krakenalt.github.io/gigaloom/)
- [Package](https://pypi.org/project/gpt2giga-harness/)
- Historical extraction context: [Source history](source-history.md)
