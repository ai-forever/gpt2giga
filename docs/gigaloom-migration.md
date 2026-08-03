# GigaLoom repository migration

GigaLoom, the local agentic workbench previously documented here as Unified
Harness, now lives in the standalone
[`krakenalt/gigaloom`](https://github.com/krakenalt/gigaloom) repository.

## What changed

- `ai-forever/gpt2giga` owns the `gpt2giga` compatibility gateway, its public
  OpenAI/Anthropic/Gemini-shaped APIs, 0.3 bridge provider profiles, deployment
  manifests, and this site.
- `krakenalt/gigaloom` owns the GigaLoom workbench, the
  `gpt2giga-harness` distribution, native-agent orchestration, Cockpit UI,
  approvals, workbench provider-launch presets, and workbench state.
- Installing `gpt2giga` does not install GigaLoom. Installing or operating
  GigaLoom follows the standalone repository.

## Legacy documentation URLs

The old Harness, agent, capability, approval, provider-authentication,
network-authority, UI-identity, and frontend-asset pages remain available here
only as migration tombstones. They are not current product documentation.

Use the [standalone GigaLoom repository](https://github.com/krakenalt/gigaloom)
for current source, installation, documentation, issues, and releases. Use this
site for the gateway's [API compatibility](api-compatibility.md),
[configuration](configuration.md), [integrations](integrations.md), and
[operations](operations.md).

## Compatibility boundary

The gateway keeps its public compatibility contracts and versioned normalized
protocol bridge. Some gateway settings and historical changelog entries retain
the word `Harness` for backward compatibility. That does not make GigaLoom an
actively owned product of this repository.

The public boundary for starting `gpt2giga` as a GigaLoom-compatible sidecar is
documented in [0.3 migration and supervisor integration](migration-0-3.md).
It uses only the installed CLI and HTTP machine contracts; there is no shared
private Python API or persistent-state migration.
