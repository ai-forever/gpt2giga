# ADR: Provider-native CLI facade and Workbench integration boundaries

Status: accepted locally for Slice C-00 on 2026-07-21. This is an
architecture-only decision. Runtime dispatch and executable contracts remain
unimplemented until later slices are activated.

## Context and scope

Phase N5 is closed at tracked commit
`0280058629e849b426166a7cb76355ed1df15ffc`. The standard Harness installation
contains Textual, and supported human terminal workflows already enter the
canonical Workbench TUI. This decision extends that accepted baseline; it does
not reopen or redesign N5.

The facade reserves exactly three root compatibility namespaces:

- `giga codex ...` for Codex CLI;
- `giga claude ...` for Claude Code;
- `giga gemini ...` for Gemini CLI.

Everything after the provider token is provider-owned syntax. No additional
namespace is reserved by this ADR, and no common execution verb is introduced.
Existing Harness commands remain owned by the current CLI.

The facade has two independent contracts. Native process compatibility is
version-independent. Workbench semantic integration is evidence- and
version-gated. They must not be represented by one provider-wide support
boolean or one combined manifest.

## Decision

### Capability levels

| Level | Owner and promise |
| --- | --- |
| L0 `native_passthrough` | The provider process owns the opaque suffix, cwd, environment, stdin, stdout, stderr, terminal topology, signals, output format, and exit status. Exact argv parity is an L0 promise, subject only to the operating system's process-launch encoding. |
| L1 `managed_handoff` | The provider owns the controlling terminal, or the existing bounded `raw-terminal-v1` line view is used. The transition is visible and makes no structured-session, typed-card, reconnect, or stream-separation claim. |
| L2 `structured_workbench` | An exact, affirmative human intent is decoded through an admitted structured transport into existing Workbench application actions and events. The canonical Textual TUI remains the only Harness-owned human frontend. |

L0 remains eligible when a provider is absent from the reviewed version
window, reports an unparseable version, cannot be probed, or introduces an
unknown suffix. Version evidence gates only L2 semantic integration. A human
workflow that cannot be represented losslessly degrades visibly to L1; flags
are never silently ignored or translated.

### Split specifications

`NativeNamespaceSpec` is the small, version-independent L0 contract. It owns:

- the public namespace and expected executable identity;
- secure `PATH`/`PATHEXT` resolution and recursion rejection;
- inherited caller environment and explicit override precedence;
- provider-owned home/config marker names for diagnostics only;
- the POSIX or Windows launcher class;
- pre-launch missing, non-executable, malformed, and recursive-target results.

It does not contain a semantic-version window, provider command inventory,
prompt classifier, structured transport, or native-home mutation authority.
It never turns executable discovery into install, authentication, update, or
execution authorization.

`WorkbenchIntegrationSpec` is the separate, versioned L1/L2 semantic contract.
It owns:

- exact upstream evidence and structured-transport admission windows;
- affirmative human-intent patterns and their precedence;
- native session selectors and lossless resume/fork meaning;
- provider-native model, effort, permission, policy, and sandbox fields;
- structured transports, event decoders, limitations, and visible L1 fallback;
- contextual capability descriptors for the current transport, process owner,
  session generation, version evidence, and policy snapshot.

Only a fully understood intent may produce a typed Workbench launch. Provider
decoders stop at the common application action/event boundary; widgets do not
inspect raw provider payloads or become an alternative application authority.

### Exact route decision

Rules are evaluated from top to bottom. Classification may inspect only the
provider token, suffix shape, TTY topology, and admitted integration evidence.
It does not persist or semantically normalize the suffix.

| Priority | Invocation/context | Route | Stable reason |
| --- | --- | --- | --- |
| 1 | First token is not `codex`, `claude`, or `gemini` | Existing Harness dispatch | `harness_root` |
| 2 | Target is missing, non-executable, recursive through `giga`, or cannot be launched safely | Fail before provider side effects | `target_unavailable` or `target_unsafe` |
| 3 | Provider-scoped help/version/completion, a machine/headless form, protocol/daemon, administration/mutation, external UI, redirected/piped form, or a suffix not affirmatively recognized as human | L0 | `native_owned` |
| 4 | Exact known human form, human TTY, admitted version and transport, and lossless typed intent | L2 | `structured_admitted` |
| 5 | Exact known human form and human TTY, but L2 evidence/transport is absent, drifted, degraded, or the typed intent would be lossy | Visible L1 | `managed_handoff` |

Provider headless precedence wins over resume/continue selectors. For example,
Claude `-p` remains L0 even when combined with `-c` or `-r`. Unknown versions
and unknown suffixes take the L0 route when the executable can be launched;
they are not blocked merely because Harness lacks semantic evidence.

### POSIX process contract

Direct L0 uses an exec-style process replacement after resolving and pinning
the provider executable to an absolute path. The implementation will use the
equivalent of `execve`/`execvpe`, preserve the original argument vector after
the executable token, inherit cwd, environment, descriptors, process group,
session, and controlling terminal, and perform no capture or post-exit work.
This makes the provider the original process for signal and exit semantics.

Resolution must reject a directory, a non-executable file, and any target with
the same file identity as the active `giga` facade. It must not fall through to
a later `PATH` entry after pinning. A lookup miss maps to the conventional
pre-exec result 127; a found but non-executable or invalid target maps to 126.
Other pre-exec failures retain a short content-free diagnostic and documented
platform errno mapping. Once `exec` succeeds, Harness has no exit-code mapping
role.

L1 supervision is a distinct, visibly managed contract and cannot claim POSIX
process replacement or invisible L0 parity.

### Windows process and shim contract

Windows has no exec-style replacement. L0 resolves the provider root once with
case-insensitive `PATHEXT` rules and then launches a child with inherited cwd,
environment, standard handles, and console. The parent performs no output
capture, does not create a new console or process group, waits for completion,
and exits with the provider process result without synthesizing POSIX signal
codes.

An `.exe` target is launched directly with the platform `CreateProcessW`
argument encoding and `shell=False`. `.cmd` and `.bat` npm-style shims use a
separate reviewed shim launcher: an absolute trusted system `cmd.exe`, explicit
`/d /s /v:off /c`, and a dedicated per-token encoder. The encoder is transport
encoding, not provider grammar parsing. It must reject NUL, CR/LF, and any token
that cannot round-trip; it must escape quotes, percent expansion, and command
metacharacters, keep delayed expansion disabled, and be tested with spaces,
empty values, Unicode, percent, exclamation, caret, ampersand, pipe,
parentheses, redirection characters, and trailing backslashes. No `shell=True`
or generic joined command string is allowed.

A shim invocation is L0 only when its complete suffix round-trips exactly. An
unrepresentable token fails before provider side effects rather than silently
changing argv. Missing targets use pre-launch result 127 and inaccessible or
invalid launchers use 126. Once the child starts, its native stdout/stderr and
normal process result remain authoritative. Windows console-control and
termination behavior is tested separately and is not described as Unix signal
equivalence.

### Privacy and authority

L0 requires no receipt. The facade must not retain, log, hash, trace, or attach
to diagnostics any raw argv/suffix, prompt, stdin, stdout, stderr, provider
response, environment value, or plain hash derived from those values.
Optional diagnostics may contain only non-content metadata such as namespace,
route level and reason, executable fingerprint/version evidence, platform
outcome, timestamps, and a reviewed command class. Diagnostics must not change
stdio, exit behavior, signals, latency-sensitive routing, or terminal state.

L1 and L2 content that the Workbench explicitly receives remains governed by
the existing redaction, terminal-neutralization, capture, retention, approval,
evidence, and application-service owners. The facade creates no native-home,
session, approval, integration, runtime, worktree, or evidence store.

## Frozen upstream evidence

The evidence below was rechecked against official upstream release and commit
pages on 2026-07-21. These refs support later semantic review; they do not limit
L0 eligibility or by themselves grant L2 admission.

| Namespace | Official repository | Release/tag | Exact release commit | Candidate L2 review window |
| --- | --- | --- | --- | --- |
| `codex` | [`openai/codex`](https://github.com/openai/codex) | [`rust-v0.144.5`](https://github.com/openai/codex/releases/tag/rust-v0.144.5) | [`87db9bc18ba5bc82c1cb4e4381b44f693ee35623`](https://github.com/openai/codex/commit/87db9bc18ba5bc82c1cb4e4381b44f693ee35623) | `>=0.144.0,<0.145.0` for separately reviewed app-server semantics |
| `claude` | [`anthropics/claude-code`](https://github.com/anthropics/claude-code) | [`v2.1.212`](https://github.com/anthropics/claude-code/releases/tag/v2.1.212) | [`67f390c9a0b1440d369aebe2ff6a5023db35bf8e`](https://github.com/anthropics/claude-code/commit/67f390c9a0b1440d369aebe2ff6a5023db35bf8e) | `>=2.1.0,<2.2.0`; no embedded durable structured-session claim |
| `gemini` | [`google-gemini/gemini-cli`](https://github.com/google-gemini/gemini-cli) | [`v0.46.0`](https://github.com/google-gemini/gemini-cli/releases/tag/v0.46.0) | [`85b0c55c126a4992b51d140e357ae9db5f9c2d7f`](https://github.com/google-gemini/gemini-cli/commit/85b0c55c126a4992b51d140e357ae9db5f9c2d7f) | `>=0.46.0,<0.47.0` for separately reviewed ACP semantics |

The windows are evidence candidates for C-01 and the provider integration
slices, not executable allowlists. Newer, older, missing, or unparsed versions
still use valid L0 routes.

## Disposition of pre-existing untracked drafts

The C-00 audit found the following untracked files in the initial checkout.
Except for this rewritten ADR, they remain unmodified, untracked, and
unaccepted.

| Draft | C-00 disposition |
| --- | --- |
| `docs/architecture/provider-native-cli-facade-adr.md` | Replaced by and adopted as this C-00 decision. The prior five-provider, combined-manifest, drift-blocking decision is superseded. |
| `packages/gpt2giga-harness/src/gpt2giga_harness/native_cli_contracts.py` | Not adopted. It combines native and structured contracts, reserves out-of-scope providers, and blocks unknown/drifted L0 forms. Audit and replace or migrate explicitly in C-01. |
| `packages/gpt2giga-harness/src/gpt2giga_harness/native_cli_capture.py` | Not adopted. Its isolated capture ideas may be reviewed in C-01, but it depends on the rejected combined manifest and is runtime code outside C-00. |
| `tests/fixtures/native_cli_contracts/command_inventory.json` | Not adopted. It contains five providers and couples native command ownership to structured version windows. Replace or migrate explicitly in C-01. |
| `tests/fixtures/native_cli_contracts/classification_cases.json` | Not adopted. It encodes out-of-scope providers and blocks version drift/unknown syntax instead of preserving L0 eligibility. Replace or migrate explicitly in C-01. |
| `tests/harness/test_native_cli_contracts.py` | Not adopted. It validates the rejected combined five-provider model. Rewrite against split contracts only after C-01 is activated. |

Their presence grants no implementation, provider execution, capture, native
home access, test authority, or acceptance evidence.

## Consequences and next gate

The early facade can remain small and forward-compatible: it recognizes three
roots and makes a process-level decision without copying volatile provider
grammars. Structured drift disables only the feature that drifted. Human
enhancement remains lossless and visible, while native machine output stays
provider-owned and ANSI/envelope-free.

This ADR changes no console dispatch, provider process, TUI code, real native
home, or network behavior. C-01 must be activated separately to implement the
split immutable contracts and hermetic evidence. No F, U, A, E, or parent N6
slice is activated by this decision.
