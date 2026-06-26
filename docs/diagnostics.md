# Compatibility Doctor

Compatibility Doctor is a protected diagnostics endpoint for explaining how
`gpt2giga` will interpret a client request before it is executed.

It is meant for support, local debugging, future UI panels, and regression
fixtures. It does not call GigaChat, does not run tools, and does not return raw
prompts, responses, headers, query values, or secrets.

## Enable the endpoint

The endpoint is part of the Admin API and is disabled by default:

```dotenv
GPT2GIGA_ADMIN_API_ENABLED=True
GPT2GIGA_ADMIN_API_KEY="<strong-admin-secret>"
```

Start the proxy as usual:

```bash
uv run gpt2giga
```

Send diagnostics requests to:

```http
POST /_admin/compat/analyze
x-admin-api-key: <strong-admin-secret>
content-type: application/json
```

`Authorization: Bearer <strong-admin-secret>` is also accepted for admin access.
Use a separate admin key, not the public proxy API key.

## Request envelope

The analyzer receives an envelope around the request you want to inspect:

```json
{
  "protocol": "openai",
  "route": "/v2/chat/completions",
  "headers": {},
  "query": {},
  "body": {}
}
```

Fields:

| Field | Required | Meaning |
|---|---:|---|
| `route` | yes | The public route that the real client would call, including `/v1`, `/v2`, or `/v1beta` prefixes when relevant. |
| `protocol` | no | One of `openai`, `anthropic`, `gemini`, `litellm`, `system`, or `unknown`. If omitted, the analyzer infers it from the route and client headers where possible. |
| `headers` | no | Headers from the client request. Sensitive header names are reported as redacted; values are not returned. |
| `query` | no | Query parameters from the client request. Sensitive query keys such as `key` are reported as redacted; values are not returned. |
| `body` | no | JSON request body. The analyzer classifies field names and tool declarations; raw prompt/response content is not returned. |

## OpenAI example

```bash
ADMIN_HEADER_NAME=x-admin-api-key
curl -sS http://localhost:8090/_admin/compat/analyze \
  -H 'content-type: application/json' \
  -H "${ADMIN_HEADER_NAME}: ${GPT2GIGA_ADMIN_API_KEY:?set GPT2GIGA_ADMIN_API_KEY}" \
  -d '{
    "protocol": "openai",
    "route": "/v2/chat/completions",
    "headers": {
      "authorization": "Bearer client-key",
      "x-request-id": "req-1"
    },
    "query": {
      "key": "query-key"
    },
    "body": {
      "model": "gpt-4o",
      "messages": [{"role": "user", "content": "redacted by diagnostics"}],
      "temperature": 0.2,
      "seed": 123,
      "tools": [
        {
          "type": "function",
          "function": {
            "name": "search_docs",
            "parameters": {"type": "object"}
          }
        },
        {"type": "web_search_preview"},
        {"type": "file_search"}
      ]
    }
  }'
```

Abbreviated response shape:

```json
{
  "protocol": "openai",
  "route": "/v2/chat/completions",
  "operation": "chat_completions",
  "backend_mode": "gigachat_v2",
  "model": {
    "requested": "gpt-4o",
    "effective": "gpt-4o",
    "pass_model": true,
    "source": "request.model"
  },
  "fields": {
    "supported": ["messages", "model", "temperature", "tools"],
    "accepted_ignored": ["seed"],
    "accepted_diagnostic_only": [],
    "approximated": [],
    "rejected": []
  },
  "tools": {
    "user_functions": ["search_docs"],
    "mapped_builtin_tools": [
      {
        "from": "web_search_preview",
        "to": "web_search",
        "reason": "provider_alias"
      }
    ],
    "unsupported_tools": ["file_search"],
    "accepted_ignored": [],
    "rejected": [],
    "details": [
      {
        "source": "openai.tools",
        "category": "provider_builtin",
        "decision": "unsupported",
        "name": "file_search",
        "reason": "unsupported_tool_type",
        "field": "tools[2].type"
      }
    ]
  },
  "security": {
    "headers_redacted": ["authorization"],
    "query_redacted": ["key"],
    "body_fields_redacted": []
  },
  "warnings": [
    {
      "code": "accepted_ignored_field",
      "message": "`seed` is accepted for compatibility but ignored.",
      "severity": "warning",
      "field": "seed"
    },
    {
      "code": "unsupported_tool",
      "message": "`file_search` is accepted for diagnostics but is not executable by the current backend.",
      "severity": "warning",
      "field": "tools"
    }
  ]
}
```

The exact field ordering and warnings can change as compatibility policies
evolve, but values that look like request content or credentials should not be
present in the response.

## Anthropic example

```bash
ADMIN_HEADER_NAME=x-admin-api-key
curl -sS http://localhost:8090/_admin/compat/analyze \
  -H 'content-type: application/json' \
  -H "${ADMIN_HEADER_NAME}: ${GPT2GIGA_ADMIN_API_KEY:?set GPT2GIGA_ADMIN_API_KEY}" \
  -d '{
    "protocol": "anthropic",
    "route": "/v2/messages",
    "headers": {
      "anthropic-version": "2023-06-01"
    },
    "body": {
      "model": "claude-3-5-sonnet-latest",
      "max_tokens": 256,
      "messages": [{"role": "user", "content": "redacted by diagnostics"}],
      "tools": [
        {"type": "custom", "name": "lookup"},
        {"type": "web_search_20250305", "name": "web_search"}
      ],
      "tool_choice": {"type": "tool", "name": "web_search"}
    }
  }'
```

The response explains supported message fields, provider tool aliases, forced
tool-choice support for the selected backend mode, and ignored Anthropic
compatibility fields.

## Gemini example

```bash
ADMIN_HEADER_NAME=x-admin-api-key
curl -sS http://localhost:8090/_admin/compat/analyze \
  -H 'content-type: application/json' \
  -H "${ADMIN_HEADER_NAME}: ${GPT2GIGA_ADMIN_API_KEY:?set GPT2GIGA_ADMIN_API_KEY}" \
  -d '{
    "route": "/v1beta/models/gemini-pro:streamGenerateContent?key=client-key",
    "query": {
      "key": "client-key"
    },
    "body": {
      "contents": [{"parts": [{"text": "redacted by diagnostics"}]}],
      "generationConfig": {"temperature": 0},
      "safetySettings": [{"category": "HARM_CATEGORY_DANGEROUS_CONTENT"}],
      "tools": [
        {"googleSearch": {}},
        {
          "functionDeclarations": [
            {
              "name": "search_docs",
              "parametersJsonSchema": {"type": "object"}
            }
          ]
        },
        {"fileSearch": {}}
      ],
      "toolConfig": {
        "functionCallingConfig": {
          "mode": "ANY",
          "allowedFunctionNames": ["search_docs"]
        }
      }
    }
  }'
```

The analyzer detects the Gemini protocol from the route, reports the effective
model from `models/{model}:operation`, redacts `key`, and separates function
declarations from Gemini provider tools such as `googleSearch` and unsupported
diagnostic-only tools such as `fileSearch`.

## Response fields

| Field | Meaning |
|---|---|
| `protocol` | Detected or supplied protocol family. |
| `route` | Route string after basic request-envelope validation. |
| `operation` | Internal operation name, such as `chat_completions`, `responses`, `messages`, `generate_content`, `stream_generate_content`, `embed_content`, or `model_info`. |
| `backend_mode` | `gigachat_v1`, `gigachat_v2`, or `unknown`, based on route prefix and `GPT2GIGA_GIGACHAT_API_MODE`. |
| `model` | Requested/effective model and whether request model passthrough is active. |
| `fields.supported` | Fields that affect execution or response behavior. |
| `fields.accepted_ignored` | Known compatibility fields accepted by the gateway but not sent upstream as executable GigaChat options. |
| `fields.accepted_diagnostic_only` | Fields retained only for diagnostics, observability summaries, or future UI explanation. |
| `fields.approximated` | Fields implemented through an approximation instead of exact provider semantics. |
| `fields.rejected` | Fields or shapes the current analyzer classifies as unexecutable. |
| `tools.user_functions` | User-defined function/tool names. |
| `tools.mapped_builtin_tools` | Provider built-in aliases mapped to GigaChat v2 built-in tool names. |
| `tools.unsupported_tools` | Tools accepted only as compatibility diagnostics and not sent as executable built-ins. |
| `tools.details` | Per-tool decisions with source, category, decision, target, reason, and field path where available. |
| `tools.mapping_disabled` | Whether `GPT2GIGA_DISABLE_BUILTIN_TOOL_MAPPING=True` affected built-in tool mapping. |
| `tools.forced_tool_choice_supported` | Whether the requested forced tool choice can be expressed for the current backend and tool shape. |
| `security` | Names of headers, query keys, and body field paths redacted from diagnostics. |
| `warnings` | Machine-readable compatibility warnings with `code`, `message`, `severity`, and optional `field`. |

## Covered operations

The current analyzer covers:

- OpenAI Chat Completions, Responses, Embeddings, Models, and LiteLLM
  `/model/info`;
- Anthropic Messages, Count Tokens, and model discovery;
- Gemini GenerateContent, StreamGenerateContent, CountTokens, EmbedContent,
  BatchEmbedContents, and model discovery;
- system route classification where applicable.

OpenAI Files/Batches, Anthropic Message Batches, and Gemini Files/Batches remain
outside the supported release surface. They can appear as unrecognized or
diagnostic-only shapes until end-to-end execution is available.

## Security notes

- The endpoint is disabled unless `GPT2GIGA_ADMIN_API_ENABLED=True`.
- The endpoint requires the admin key, not the public proxy key.
- The analyzer does not call the upstream GigaChat client.
- Sensitive headers and query keys are reported by name only.
- Secret-like body paths are reported by path only.
- Prompt and response content are not echoed.
- The endpoint is for diagnostics; it does not prove that a live upstream request
  will succeed.

For the broader route matrix, see [API compatibility](api-compatibility.md). For
parameter-level policy, see [Client parameter compatibility](client-parameter-compatibility.md).
