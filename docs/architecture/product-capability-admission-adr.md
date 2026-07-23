# ADR: Product vocabulary and capability admission

Status: accepted for GigaLoom roadmap slice G0-01 on 2026-07-23.

## Context

Workbench currently exposes legacy mode and transport terms such as `plan`,
`read`, `edit`, `headless`, `native_structured`, `native_terminal`, `one_shot`,
and `stream`. These terms mix operator intent, authority, provider transport,
and presentation. That makes unsupported combinations easy to imply and makes
ordinary users choose implementation details.

## Decision

Schema version 1 has six independent vocabularies:

- `TaskIntent`: `ask`, `review`, or `change`;
- `AuthorityLevel`: `read_only` or `workspace_write`;
- `TransportCapability`: `structured_session`, `terminal_session`, `one_shot`,
  or `streaming_events`;
- `ToolCapability`: filesystem read/write, process, network, GitHub, browser,
  MCP, or child-agent authority;
- `TitleProvenance`: `untitled`, `legacy`, `fallback`, `provider_native`, or
  `manual`;
- `IntegrationLifecycle`: `definition_only`, `enabled`, `disabled`,
  `uninstalled`, or `definition_deleted`.

The ordinary UI may ask for task intent and authority. Transport is selected
by backend admission from source-derived provider evidence. Tool authority is
admitted independently and can never exceed the selected authority level.
Title provenance and integration lifecycle are durable state, not UI labels or
overloaded action verbs.

Admission returns exactly one of `available`, `degraded`, or `blocked`, plus
stable `why`, recovery, and bounded diagnostics fields. Missing or unknown
evidence is blocked. A downgrade is valid only when it is explicit, visible,
and preserves the requested authority boundary.

The Python authority for these values, their manifest, and admission behavior
is `gpt2giga_harness.product_capabilities`. UI and documentation projections
must derive from its versioned manifest rather than duplicate provider claims.

## Compatibility window

Machine API and CLI fields remain readable during the G0/G1/G2 migration:

| Legacy field/value | Product mapping | Rule |
| --- | --- | --- |
| `mode=plan` | `ask` + `read_only` | Compatibility alias; planning semantics remain visible. |
| `mode=read` | `review` + `read_only` | Compatibility alias. |
| `mode=edit` | `change` + `workspace_write` | Compatibility alias. |
| `execution_transport=native_structured` | `structured_session` | Provider evidence still gates admission. |
| `execution_transport=native_terminal` | `terminal_session` | Machine-only override. |
| `execution_transport=one_shot` | `one_shot` | Machine-only compatibility override. |
| `invocation_mode=headless` | no mapping | It does not prove a transport and cannot be guessed. |
| `stream=true` | `streaming_events` | Compatibility request, not an ordinary UI toggle. |
| `stream=false` | no capability | Compatibility opt-out only. |

An unknown value fails before execution. Compatibility aliases may be removed
only after tracked callers, stored state, API fixtures, CLI documentation, and
supported clients have migrated; one released compatibility window and an
explicit removal notice are required. `plan` and `read` remain distinguishable
until their callers and artifacts prove that collapsing them is safe.

## Consequences

G1 and G2 may consume this contract but must not add local vocabulary variants.
This ADR does not change existing machine payloads, migrate stored sessions,
select a provider route, grant a tool, or repair Automation. Those changes
remain owned by their later roadmap slices.
