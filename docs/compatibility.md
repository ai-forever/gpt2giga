# Compatibility matrix

`gpt2giga` maps OpenAI-, Anthropic- and Gemini-shaped client APIs to GigaChat.
This page is the short release matrix. Detailed route status and edge-case
behavior are documented in [API compatibility](api-compatibility.md).

## Public surface summary

| Surface | Non-stream | Stream | Tools | Structured output | Embeddings | Models | Token count |
|---|---:|---:|---:|---:|---:|---:|---:|
| OpenAI Chat | yes | yes | yes | yes | n/a | yes | n/a |
| OpenAI Responses | yes | yes | yes | yes | n/a | n/a | n/a |
| Anthropic Messages | yes | yes | yes | yes | n/a | yes | yes |
| Gemini generateContent | yes | yes | yes | yes | n/a | yes | yes |
| Gemini embeddings | n/a | n/a | n/a | n/a | yes | yes | n/a |
| LiteLLM model info | n/a | n/a | n/a | n/a | n/a | yes | n/a |

## Gemini release scope

Supported Gemini-compatible operations:

- `generateContent`
- `streamGenerateContent`
- `countTokens`
- `embedContent`
- `batchEmbedContents`
- model discovery

Supported Gemini prefixes:

- root operation paths such as `/models/{model}:generateContent`
- `/v1/models/{model}:generateContent`
- `/v2/models/{model}:generateContent`
- `/v1beta/models/{model}:generateContent`
- `/v1/v1beta/models/{model}:generateContent`
- `/v2/v1beta/models/{model}:generateContent`

Prepared but not release-supported until end-to-end upstream execution is
validated:

- Gemini Files API
- Gemini `batchGenerateContent`
- OpenAI Files API
- OpenAI Batches API
- Anthropic Message Batches API

## Compatibility limits

Some client fields are accepted so SDKs do not fail before the useful request
reaches GigaChat, but they are not enforced by GigaChat execution. For Gemini,
that includes `safetySettings`, `cachedContent`, some generation controls,
unsupported non-function tools, and non-text embedding parts.

Auth query parameters such as Gemini `?key=...` are accepted for client
compatibility, but header-based auth is preferred. Runtime logs, traffic logs,
observability attributes, and metrics labels must not contain raw API keys.
