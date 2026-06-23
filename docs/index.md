# gpt2giga documentation

`gpt2giga` is a FastAPI compatibility gateway that accepts requests in the OpenAI, Anthropic, and Gemini formats and forwards them to GigaChat. It is useful when a client, editor, agent framework, or SDK can talk to the OpenAI/Anthropic/Gemini API, but the real backend must be GigaChat.

Default local address:

```text
http://localhost:8090
```

## What the proxy covers

| Capability | Where to read |
|---|---|
| Quick start via Docker Compose or `uv` | [Quickstart](quickstart.md) |
| Supported OpenAI, Anthropic, Gemini, and LiteLLM routes | [API compatibility](api-compatibility.md) |
| Behavior of `extra_headers`, `extra_query`, `extra_body`, and optional fields | [Client parameters](client-parameter-compatibility.md) |
| GigaChat built-in tools and their mapping to OpenAI/Anthropic/Gemini | [Built-in tools](builtin-tools.md) |
| Environment variables, authentication, limits, metrics, observability | [Configuration](configuration.md) |
| GigaFusion behavior, presets and request examples | [GigaFusion](fusion.md) |
| How to choose between benchmark Fusion and tool-agent Fusion | [GigaFusion guide](fusion-guide.md) |
| Compose profiles, Traefik, nginx, Postgres, OpenSearch, Phoenix | [Deployment](deployment.md) |
| Runtime logs, traffic logs, admin API, debug translate | [Operations](operations.md) |
| Editor, agent, SDK, and reverse-proxy setup | [Integrations](integrations.md) |

## Current API surface

Public routes are available at the root and under versioned prefixes:

- `/chat/completions`, `/v1/chat/completions`, `/v2/chat/completions`
- `/responses`, `/v1/responses`, `/v2/responses`
- `/embeddings`, `/v1/embeddings`, `/v2/embeddings`
- `/messages`, `/v1/messages`, `/v2/messages`
- `/v1beta/models/{model}:generateContent` and compatible Gemini paths
- `/models`, `/model/info`, `/health`, `/ping`

The backend selection rule is the same for OpenAI-, Anthropic-, and
Gemini-compatible routes: `/v1/...` always sends chat-like requests to the
GigaChat v1 contract, `/v2/...` sends them to the GigaChat v2 contract, and the
root path without `/v1` or `/v2` uses `GPT2GIGA_GIGACHAT_API_MODE=v1|v2`.

OpenAI Files/Batches, Anthropic Message Batches, and Gemini Files/Batches are prepared in the code but intentionally not mounted until end-to-end execution is available in the upstream SDK/backend.

## Fast path

1. Copy `.env.example` to `.env`.
2. Fill in `GIGACHAT_CREDENTIALS`, `GIGACHAT_SCOPE`, `GIGACHAT_MODEL`.
3. Run `docker compose --env-file .env -f deploy/base.yaml --profile DEV up -d`.
4. Check `curl http://localhost:8090/health`.
5. Point the SDK at `http://localhost:8090/v1` or `http://localhost:8090/v2` for an explicit backend contract, or at `http://localhost:8090` if the root should follow `GPT2GIGA_GIGACHAT_API_MODE`.

## For developers

- [Normalized messages](architecture/normalized-messages.md) describes the experimental layer of protocol-independent models.
- [Logging and observability](architecture/logging-and-observability.md) sets the boundaries between runtime logs, traffic logs, metrics, and traces.
- [Fusion provider architecture](architecture/fusion-provider.md) describes the internal Fusion orchestration boundary.
- [Adding a provider or protocol](architecture/how-to-add-provider.md) gives a checklist for extending the public protocol surface and upstream providers.
