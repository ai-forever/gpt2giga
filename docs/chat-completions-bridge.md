# Use Codex, Claude Code, and Gemini CLI with a Chat Completions server

This guide configures one immutable OpenAI-compatible
`/v1/chat/completions` server as the upstream for three client protocols:

```text
Codex (Responses) ───────────┐
Claude Code (Messages) ──────┼─> gpt2giga ─> /v1/chat/completions
Gemini CLI (GenerateContent) ┘
```

The route is a technical preview. gpt2giga translates only the reviewed
chat-like subset and rejects unsupported meaning before contacting the
upstream. It does not pretend that Chat Completions implements every feature of
Responses, Messages, or GenerateContent.

## What the upstream must support

You need:

- the exact Chat Completions endpoint or its API base URL;
- the exact upstream model id;
- the real context, input, and output token limits;
- an optional bearer token;
- non-streaming Chat Completions JSON;
- Chat Completions SSE with a terminal `data: [DONE]` frame;
- function tools and tool calls if the coding clients should use local tools.

The gateway requests stream usage with
`stream_options: {"include_usage": true}`. Missing usage remains missing; the
gateway never invents token counts.

## 1. Declare the upstream

Create `providers.yaml` outside the repository:

```yaml
schema_version: gpt2giga.provider-profiles.v3
profiles:
  - profile_id: chat-only-upstream
    provider_kind: openai_compatible
    base_url: https://inference.example/v1/chat/completions
    credential_env: CHAT_UPSTREAM_API_KEY
    network_policy_ref: public-openai
    tls_policy_ref: system-default
    models:
      - public_alias: bridge/chat-only
        upstream_model: exact-upstream-model-id
        capability_profile: chat-only-coding-v1
        capabilities:
          features:
            - roles
            - ordered_content_parts
            - text
            - generation_controls
            - function_tools
            - tool_choice
            - parallel_tool_calls
            - tool_results
            - stream_deltas
            - stream_terminal_events
            - stop_reason
            - usage
            - model_identity
            - request_error_classes
            - cancellation
            - context_token_limits
          limits:
            context_window: 32768
            max_input_tokens: 28672
            max_output_tokens: 4096
        support_status: technical_preview
```

Replace the endpoint, model id, and limits. The public alias is the model name
used by all three clients; it is mapped to `upstream_model` only inside the
gateway.

Remove `credential_env` when the upstream is intentionally keyless. When it is
present, gpt2giga reads the named variable at startup and sends its value as a
bearer token. A client cannot override the destination, upstream model, or
upstream credential.

The `features` list is an allowlist, not a wish list. Add
`json_schema_output` or `image_references` only after the exact upstream model
has been verified to support them. Do not add `count_tokens`: a Chat
Completions endpoint has no exact token-count operation.

The endpoint may also be written as `https://inference.example/v1`; gpt2giga
then appends `chat/completions`. A full endpoint ending in
`/chat/completions` is used unchanged.

### Local upstream

For a server on the same host, use the explicit loopback exception:

```yaml
    base_url: http://127.0.0.1:8001/v1/chat/completions
    allow_loopback: true
    network_policy_ref: loopback-development
```

Direct private, link-local, and metadata-network destinations are rejected. For
a server reachable only through a VPN or private subnet, create an SSH or
equivalent tunnel to loopback and use the loopback profile.

## 2. Start gpt2giga

From a source checkout:

```sh
export CHAT_UPSTREAM_API_KEY='<upstream-bearer-token>'
export GPT2GIGA_CONFIG=/absolute/path/to/providers.yaml
export GPT2GIGA_ENABLE_API_KEY_AUTH=True
export GPT2GIGA_API_KEY='<local-gateway-key>'

uv run gpt2giga
```

For a keyless upstream, omit `CHAT_UPSTREAM_API_KEY`. With an installed
package, run `gpt2giga` instead of `uv run gpt2giga`.

Check readiness and the static model alias without contacting the inference
server:

```sh
curl -fsS http://127.0.0.1:8090/ready
curl -fsS \
  -H "Authorization: Bearer $GPT2GIGA_API_KEY" \
  http://127.0.0.1:8090/v1/models
```

Then test the actual translation:

```sh
curl -fsS http://127.0.0.1:8090/v1/responses \
  -H "Authorization: Bearer $GPT2GIGA_API_KEY" \
  -H 'Content-Type: application/json' \
  -d '{"model":"bridge/chat-only","input":"Reply only OK"}'
```

## 3. Connect Codex

Add the provider to `~/.codex/config.toml`:

```toml
[model_providers.gpt2giga_chat]
name = "gpt2giga Chat bridge"
base_url = "http://127.0.0.1:8090/v1"
env_key = "GPT2GIGA_API_KEY"
wire_api = "responses"
requires_openai_auth = false
supports_websockets = false
```

Create the separate profile file `~/.codex/chat-bridge.config.toml`:

```toml
model = "bridge/chat-only"
model_provider = "gpt2giga_chat"
model_context_window = 32768
model_auto_compact_token_limit = 24576
model_supports_reasoning_summaries = false
model_reasoning_summary = "none"
web_search = "disabled"
```

Export the gateway key and select the profile:

```sh
export GPT2GIGA_API_KEY='<local-gateway-key>'
codex --profile chat-bridge
```

### Minimal Codex benchmark command

For a hermetic CLI benchmark, bypass user MCP, app, plugin, and multi-agent
configuration and provide the bridge settings explicitly:

```sh
codex -a never exec --json \
  --ignore-user-config \
  --strict-config \
  --skip-git-repo-check \
  --ephemeral \
  --sandbox workspace-write \
  --disable apps \
  --disable plugins \
  --disable multi_agent \
  --disable apply_patch_freeform \
  -m bridge/chat-only \
  -c model_provider=gpt2giga_chat \
  -c model_providers.gpt2giga_chat.name=gpt2giga_chat \
  -c model_providers.gpt2giga_chat.base_url=http://127.0.0.1:8090/v1 \
  -c model_providers.gpt2giga_chat.env_key=GPT2GIGA_API_KEY \
  -c model_providers.gpt2giga_chat.wire_api=responses \
  -c model_providers.gpt2giga_chat.supports_websockets=false \
  -c model_reasoning_effort=none \
  -c web_search=disabled \
  'Complete the benchmark task.'
```

The same command string can be passed to a benchmark runner such as
`harness_bench run-cli`. Codex CLI 0.146.0 was verified with this exact
minimal surface: `exec_command`, `write_stdin`, `update_plan`,
`request_user_input`, and `view_image`, all represented as ordinary function
tools. A live two-turn probe completed a streamed `exec_command`, returned its
result, and received the final model answer through the Chat Completions
upstream.

Responses custom/freeform tools are deliberately outside this bridge subset.
In particular, do not enable `apply_patch_freeform`. With the unknown public
model alias used above, current Codex falls back to shell-based edits through
`exec_command`; it does not expose `apply_patch`. If a benchmark requires the
custom `apply_patch` wire contract itself, it needs a native Responses upstream
or a separately reviewed custom-tool extension.

Codex uses the Responses wire API. The bridge accepts its stateless Responses
envelope, maps `developer` messages to Chat Completions `system` messages,
flattens namespace tools before the upstream call, and restores their namespace
in returned function calls. It accepts the server-generated item ids replayed
by Codex and preserves function call ids through the following
`function_call_output` turn.

The current Codex CLI may warn that `/v1/models` does not contain its richer
Codex-specific model metadata. gpt2giga intentionally returns the standard
OpenAI model-list shape and Codex falls back to the explicit profile values
above. This warning does not prevent a request.

Codex configuration fields and profile-file precedence are documented in the
[official Codex configuration reference](https://learn.chatgpt.com/docs/config-file/config-basic).

## 4. Connect Claude Code

Keep Claude Code inside the stateless Messages subset and align its limits with
the provider profile:

```sh
export ANTHROPIC_BASE_URL=http://127.0.0.1:8090
export ANTHROPIC_API_KEY="$GPT2GIGA_API_KEY"
export ANTHROPIC_MODEL=bridge/chat-only
export ANTHROPIC_SMALL_FAST_MODEL=bridge/chat-only

export CLAUDE_CODE_MAX_CONTEXT_TOKENS=32768
export CLAUDE_CODE_MAX_OUTPUT_TOKENS=4096
export MAX_THINKING_TOKENS=0
export CLAUDE_CODE_DISABLE_THINKING=1
export DISABLE_PROMPT_CACHING=1
export CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1

claude --model bridge/chat-only
```

`ANTHROPIC_API_KEY` makes Claude Code send the local gateway key as
`x-api-key`. The bridge also accepts bearer authentication.

Thinking and prompt caching are disabled because Chat Completions cannot
preserve those Anthropic semantics. `CLAUDE_CODE_MAX_OUTPUT_TOKENS` must not
exceed `capabilities.limits.max_output_tokens`; an unknown Claude model
otherwise defaults to a much larger output limit. Claude Code can use ordinary
function tools and streaming Messages events through this route.

Some Claude Code workflows call `/v1/messages/count_tokens`. This bridge
rejects that operation instead of returning an estimate. Core chat and tool
execution do not require an exact count-token endpoint, but a feature that does
will remain unavailable.

See the [official Claude Code environment-variable reference](https://code.claude.com/docs/en/env-vars)
for the client-side variables.

## 5. Connect Gemini CLI

Gemini CLI gives unknown model names its built-in `chat-base` configuration,
which currently adds `topK` and `thinkingConfig`. Those controls have no exact
Chat Completions representation and are rejected. Define a minimal custom alias
whose key is the exact public model id.

Merge this block into `~/.gemini/settings.json`:

```json
{
  "security": {
    "auth": {
      "selectedType": "gemini-api-key"
    }
  },
  "modelConfigs": {
    "customAliases": {
      "bridge/chat-only": {
        "modelConfig": {
          "model": "bridge/chat-only",
          "generateContentConfig": {
            "temperature": 1,
            "topP": 0.95,
            "maxOutputTokens": 4096
          }
        }
      }
    }
  }
}
```

Do not extend `chat-base`, and do not add `topK` or `thinkingConfig` for this
route. The alias key must remain `bridge/chat-only`: after a tool call, Gemini
CLI continues with the resolved model id, so a differently named alias would
only control the first request.

Start Gemini CLI with the public model id:

```sh
export GOOGLE_GEMINI_BASE_URL=http://127.0.0.1:8090
export GEMINI_API_KEY="$GPT2GIGA_API_KEY"
export GEMINI_MODEL=bridge/chat-only
export OTEL_SDK_DISABLED=true

gemini --model bridge/chat-only
```

Gemini sends `GEMINI_API_KEY` as Google-style API-key authentication, which the
gateway accepts as its local API key. The provider profile then resolves the
public model id to the exact upstream model. Gemini CLI's synthetic
`skip_thought_signature_validator` marker is accepted only as a client-side
no-op; an actual thought signature remains unsupported.

If `GEMINI_CLI_HOME` is set, Gemini CLI treats it as a home root. Put the global
settings at `$GEMINI_CLI_HOME/.gemini/settings.json`, not directly in
`$GEMINI_CLI_HOME`.

If the alias is stored in project-local `.gemini/settings.json`, trust that
workspace before use. In headless runs, set
`GEMINI_CLI_TRUST_WORKSPACE=true` before starting Gemini CLI so the workspace
settings are loaded.

The model configuration format is described in the
[official Gemini CLI advanced model configuration guide](https://github.com/google-gemini/gemini-cli/blob/main/docs/cli/generation-settings.md).

## Supported subset and deliberate limits

The bridge supports text roles, common generation controls, function tools and
results, tool choice where the target protocol can express it, streaming,
terminal stop reasons, usage when returned by the upstream, cancellation, and
declared context limits.

A complete stateless tool loop is supported: the client sends function
definitions, receives a streamed or non-streamed call, executes it locally,
and replays the call plus its result in the next request. The bridge preserves
the call id and translates the next turn back to Chat Completions. This was
verified for Responses, Anthropic Messages, and Gemini GenerateContent.

It does not emulate:

- Responses state such as `previous_response_id`, conversations, background
  jobs, or durable `store` behavior;
- reasoning/thinking or reasoning summaries;
- prompt-cache semantics and exact cached-token accounting;
- hosted web search, computer use, code execution, or provider-native tools;
- Responses custom/freeform tools such as `apply_patch`;
- files, audio, and unsupported multimodal content;
- exact token counting;
- Gemini safety settings, cached content, `topK`, or thinking configuration.

Operational no-op fields emitted by the tested clients are accepted where they
do not change the translated request. A semantic field outside the reviewed
subset returns `unsupported_semantic` before upstream I/O.

## Troubleshooting

| Symptom | Meaning and action |
|---|---|
| `unknown_model_alias` | The client must use the exact `public_alias`, including case and punctuation. |
| `credential_unavailable` at startup | Set the variable named by `credential_env`, or remove that field for a deliberately keyless upstream. |
| `unsupported_semantic` | The client sent meaning that Chat Completions cannot preserve. Disable that client feature; do not add a capability unless the upstream was actually verified. |
| Request rejected for token limits | Align the client context/output settings with the exact values in the profile. |
| Gemini request mentions `topK` or `thinkingConfig` | Define the minimal custom alias under the exact public id `bridge/chat-only`; a differently named alias applies only to the first tool-loop request. |
| Claude asks for `count_tokens` | That operation is deliberately unsupported for a Chat Completions-only upstream. |
| Codex model-metadata warning | Keep the explicit context and compaction values in the Codex profile; standard requests still proceed. |
| `provider_protocol_error` during streaming | Verify that the upstream emits valid Chat Completions SSE, a terminal choice, optional usage in the correct order, and `[DONE]`. |

For the profile schema and routing security contract, see
[Provider profiles and model aliases](provider-profiles.md). For the semantic
admission rules, see [Bridge compatibility, loss, and errors](bridge-compatibility.md).
