# Agents and multi-agent behavior in GigaLoom

GigaLoom exposes several things called an “agent,” but they do not share one
runtime, identity, or authority model. This guide explains which layer owns an
action, what can cross between layers, and which commands describe the current
product.

The short rule is:

- **Direct Chat** is a GigaChat model conversation through the `gpt2giga`
  gateway.
- **Coding Agent** starts Codex CLI, Claude Code, or Gemini CLI through a
  reviewed adapter.
- a **GigaLoom Agent profile** is reusable configuration for one coding-agent
  run; it is not a spawned native provider subagent;
- **Arena** compares independent runs;
- a **Workflow** coordinates durable child jobs and passes bounded visible
  summaries or artifacts;
- **native Codex subagents** are created and orchestrated inside Codex. GigaLoom
  does not turn them into Harness workflow children or transfer their private
  state.

## Choose the right surface

| Surface | Use it for | Execution owner | What GigaLoom retains |
| --- | --- | --- | --- |
| Direct Chat | Questions, drafting, GigaChat built-in tools | GigaChat through the local gateway | Visible messages, normalized events, admitted tool records, and provider-emitted usage |
| Coding Agent | Repository exploration, review, or isolated edits | Selected Codex, Claude, or Gemini CLI process | Run/session identity, bounded events, artifacts, policy receipts, and adapter evidence |
| Agent profile | A repeatable role, model, instructions, tools, and policy | The coding-agent adapter named by the profile | Immutable redacted profile and execution-plan snapshots |
| Arena | Side-by-side comparison of one task | Independent ordinary durable runs | One parent comparison plus each child session/run |
| Workflow | A validated DAG with bounded fan-out, approvals, joins, and handoffs | Durable coordinator plus ordinary child jobs | Definition hash, step snapshots, visible handoffs, artifacts, and child run links |
| Native Codex subagents | Parallel delegated work inside a Codex turn | Codex parent thread and its agent threads | Only what the outer Codex adapter emits as visible output or artifacts |

Direct Chat is not a repository tool loop. Coding Agent is not a generic
provider-neutral login or permission system. Switching between the two cannot
silently change the selected task intent or workspace authority.

## Native Codex subagents

[OpenAI’s current subagent guide](https://learn.chatgpt.com/docs/agent-configuration/subagents)
describes Codex subagents as separate agent threads spawned for bounded work and
summarized back to the main thread. Current Codex clients can show those
threads; the CLI uses `/agent` to inspect and switch between them.

The important authority boundary is also provider-owned:

- a Codex subagent inherits the parent turn’s current sandbox and permission
  mode;
- live runtime overrides are reapplied when the child starts;
- a custom agent may narrow itself, for example to read-only;
- a child does not gain a broader sandbox merely because its model or custom
  agent configuration differs;
- if a non-interactive run cannot surface a required new approval, the action
  fails and is reported back to the parent.

GigaLoom does not inspect Codex private reasoning, copy a native Codex thread
into another provider, or convert native subagents into Harness Agent profiles.
From GigaLoom’s point of view, they remain behavior inside the admitted Codex
process or app-server session.

## GigaLoom Agents, Arena, and Workflows

A project Agent profile under `.giga/agents/*.yaml` is a versioned recipe over
an existing harness. It can select instructions, model, reasoning effort,
workspace/permission policy, managed MCP ids, budgets, and an expected
artifact. Unsupported options fail before queueing. A profile does not contain
literal secrets or arbitrary provider flags.

Arena creates independent child sessions and durable runs for comparison. A
follow-up targets a specific child. The parent view multiplexes visible events,
but it does not merge provider-native histories or make one child’s authority
available to another.

A Workflow is a validated DAG. Its agent, arena, and eval steps submit ordinary
durable jobs. Each child receives an immutable profile and execution-plan
snapshot. Editing children are forced into distinct detached Git worktrees;
their patches remain reviewable until the operator explicitly chooses,
discards, or applies them. Bounded handoffs contain only visible summaries and
selected artifact references—never hidden reasoning.

Workflow membership is not a generic child-agent grant. Every child is admitted
as its own run under explicit policy. The future scoped-authority work may
further unify child ceilings, but this guide does not claim that unimplemented
contract.

Source authorities:

- [`agents.py`](https://github.com/ai-forever/gpt2giga/blob/main/packages/gpt2giga-harness/src/gpt2giga_harness/agents.py)
  owns Agent profile parsing, snapshots, and execution plans;
- [`arena.py`](https://github.com/ai-forever/gpt2giga/blob/main/packages/gpt2giga-harness/src/gpt2giga_harness/arena.py)
  owns independent comparison children and evidence;
- [`workflows.py`](https://github.com/ai-forever/gpt2giga/blob/main/packages/gpt2giga-harness/src/gpt2giga_harness/workflows.py)
  owns the validated DAG and bounded handoffs;
- [`runtime/policy.py`](https://github.com/ai-forever/gpt2giga/blob/main/packages/gpt2giga-harness/src/gpt2giga_harness/runtime/policy.py)
  owns Harness policy and approval receipts;
- [`worktrees.py`](https://github.com/ai-forever/gpt2giga/blob/main/packages/gpt2giga-harness/src/gpt2giga_harness/worktrees.py)
  owns isolated edit delivery.

## Authentication, approvals, and tools

Authentication has two current paths:

- Direct Chat uses the gateway credential boundary and `SecretRef` handling;
- Codex, Claude, and Gemini native CLIs own their own login, refresh, credential
  storage, logout, and revocation.

GigaLoom's native login broker can start provider-owned login, status, logout,
and revocation operations and bind admitted account evidence to a session. The
provider CLI still owns credentials and refresh behavior. An installed binary
alone never proves that an account is ready.

Approvals are similarly split. Harness approvals cover actions Harness owns,
such as process admission, integration mutation, or applying a retained patch.
Interactive prompts inside an external CLI remain provider-owned. An outer
Harness approval receipt is not evidence that every internal provider action
was observed or approved by Harness.

Tool names do not cross boundaries automatically:

- Direct Chat can use the admitted GigaChat built-ins: `web_search`,
  `url_content_extraction`, `code_interpreter`, `image_generate`, and
  `model_3d_generate`;
- reviewed MCP descriptors selected for a coding-agent run are frozen into an
  immutable redacted snapshot and materialized only at the execution boundary;
- Skills and Plugins can be discovered, reviewed, installed, enabled, or
  disabled, but catalog presence alone grants no runtime authority and proves
  no automatic prompt or tool injection;
- unavailable or unknown capabilities fail closed before provider execution.

The independent intent/authority vocabulary comes from
[`product_capabilities.py`](https://github.com/ai-forever/gpt2giga/blob/main/packages/gpt2giga-harness/src/gpt2giga_harness/product_capabilities.py):
`Ask`, `Review`, and `Change` never broaden `Read only` or `Workspace write`.

## Continuity, cancellation, cost, and evidence

Continuity is route-specific. Direct Chat replays normalized visible history.
Codex can use a supervised app-server thread when its version-probed capability
is available. Claude and Gemini headless paths are one-shot; their native
resume contracts are separate and remain bounded by adapter evidence.

Cancellation is cooperative. GigaLoom persists cancellation intent and asks the
admitted route to stop, but it cannot roll back a provider action that already
completed.

Usage and cost are not synonyms. GigaLoom retains provider-emitted token or
usage evidence when available. Monetary cost stays `unknown` unless the
provider returns explicit cost evidence; the product does not estimate a
subscription price or infer certainty from token counts.

Only visible messages, summaries, normalized events, redacted terminal output,
and retained artifacts may cross a Harness boundary. GigaLoom does not claim:

- hidden reasoning or private chain-of-thought transfer;
- provider-native session transfer between Codex, Claude, Gemini, or Direct
  Chat;
- complete visibility into a black-box provider process;
- automatic delegation without an admitted Arena, Workflow, or native-provider
  operation.

## Exact supported commands

Start the product surfaces:

```bash
giga ui
giga chat "Summarize the trade-offs"
giga run --agent codex --mode read "Review this repository"
```

Create and continue a retained session:

```bash
giga session create --harness codex-cli --workspace . --json
giga session turn <session_id> --prompt "Review the current diff" --json
giga session events <run_id> --json
giga session approve <approval_id> --decision allow_once --json
```

Inspect and run Agent profiles:

```bash
giga agent list --workspace .
giga agent show reviewer --workspace . --json
giga agent validate .giga/agents/reviewer.yaml
giga agent run reviewer --workspace . --prompt "Review this patch" --dry-run
```

Inspect and run Workflows:

```bash
giga workflow list --workspace .
giga workflow show review-team --workspace . --json
giga workflow validate .giga/workflows/review-team.yaml
giga workflow run review-team --workspace . --prompt "Review this change" --json
giga workflow status <workflow_run_id> --json
giga workflow cancel <workflow_run_id>
```

Inspect the current source-derived contracts:

```bash
giga harness list --json
giga harness inspect codex-cli --json
giga harness capabilities
giga harness capabilities --agents
giga harness capabilities --agents --json
giga harness capabilities --inventory --json
```

Arena is currently a Web/API surface rather than a separate `giga arena`
command. Open **Evaluation → Arena** in `giga ui`, or use the authenticated
`/api/arena/runs` routes documented in the
[Harness architecture](architecture/harness.md#arena-policy-approvals-and-attention).

## Generated capability matrix

The versioned product inventory is generated from product schemas, built-in
registries, installed entry points, provider compatibility profiles, the CLI
parser, TUI command registry, API routes, and contract tests. The first-run
doctor includes its schema, version, digest, provider contracts, and
documentation ids. Inspect it with:

```bash
giga harness capabilities --inventory --json
```

The [agent surface capability matrix](agent-capability-matrix.md) is a
projection of the same inventory. Regenerate its exact Markdown with:

```bash
giga harness capabilities --agents
```

CI runs `giga harness capabilities --inventory --check`. It verifies the
packaged inventory digest, CLI/TUI/API surfaces, protocol, transport, mode and
deprecation records, local documentation targets, contract-test evidence, and
the generated English/Russian matrix cells.
