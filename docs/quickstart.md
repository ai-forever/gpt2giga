# Quickstart

This document helps you launch an OpenAI-, Anthropic-, and Gemini-compatible
gateway to GigaChat and verify each protocol with a first request.

## Requirements

- Python 3.10–3.14 for a local run.
- `uv` for local development.
- Docker with the Compose plugin for a container run.
- GigaChat credentials and scope for the target account.

## Setting up credentials

Create a local env file:

```sh
cp .env.example .env
```

At a minimum, fill in:

```dotenv
GPT2GIGA_MODE=DEV
GPT2GIGA_HOST=0.0.0.0
GPT2GIGA_PORT=8090
GPT2GIGA_ENABLE_API_KEY_AUTH=True
GPT2GIGA_API_KEY="<local-proxy-api-key>"
GIGACHAT_CREDENTIALS="<your-gigachat-credentials>"
GIGACHAT_SCOPE=GIGACHAT_API_PERS
GIGACHAT_MODEL=GigaChat-2-Max
```

The GigaChat SDK settings use the `GIGACHAT_` prefix. The proxy settings use the `GPT2GIGA_` prefix.

## Running via Docker Compose

DEV profile:

```sh
docker compose --env-file .env -f deploy/base.yaml --profile DEV up -d
```

PROD profile:

```sh
docker compose --env-file .env -f deploy/base.yaml --profile PROD up -d
```

In `PROD`, the Compose file binds the service to `127.0.0.1` only by default. For external access, put nginx, Traefik, Caddy, or another reverse proxy in front.

Check:

```sh
curl http://localhost:8090/health
```

## Choose an installation

Install only the compatibility gateway when you need the OpenAI-, Anthropic-,
or Gemini-shaped HTTP API:

```sh
uv tool install --prerelease allow gpt2giga
gpt2giga
```

The current Unified Harness alpha runs from the source checkout described in
the [Unified Harness guide](harness.md). After the standalone package appears
in your package index, install the local control plane with:

```sh
uv tool install gpt2giga-harness
giga doctor
giga ui
```

The Harness distribution uses the `gpt2giga_harness` Python namespace and
provides the `giga` and `gpt2giga-harness` commands. The gateway distribution
provides only the `gpt2giga` command.

:::warning[Alpha preview]

Unified Harness is under active development. Start with local, supervised
workflows and read the [Unified Harness alpha guide](harness.md) before enabling
edit mode, remote access, or scheduled jobs.

:::

## Run from the repository

Install both editable workspace members and the development dependencies:

```sh
uv sync --all-packages --all-extras --dev
uv run gpt2giga
```

In `DEV`, the FastAPI docs are available at `http://localhost:8090/docs`. In `PROD` they are disabled.

## OpenAI SDK

```python
from openai import OpenAI

api_version = "v1"
client = OpenAI(
    base_url=f"http://localhost:8090/{api_version}/",
    api_key="<local-proxy-api-key>",
)

completion = client.chat.completions.create(
    model="GigaChat-2-Max",
    messages=[{"role": "user", "content": "Briefly explain SSE"}],
)
print(completion.choices[0].message.content)
```

To explicitly select the GigaChat backend contract, use `api_version = "v1"`
or `api_version = "v2"` and pass it into `base_url`. `/v1` always selects the
GigaChat v1 contract, `/v2` selects the GigaChat v2 contract.
`http://localhost:8090` without a version follows `GPT2GIGA_GIGACHAT_API_MODE=v1|v2`.

## Anthropic SDK

```python
from anthropic import Anthropic

api_version = "v1"
client = Anthropic(
    base_url=f"http://localhost:8090/{api_version}/",
    api_key="<local-proxy-api-key>",
)

message = client.messages.create(
    model="GigaChat-2-Max",
    max_tokens=512,
    messages=[{"role": "user", "content": "Briefly explain SSE"}],
)
print(message.content[0].text)
```

## Gemini SDK

The official Gemini client appends `/v1beta/models/...` itself, so pass the
gateway root rather than `/v1` or `/v2`:

```python
from google import genai
from google.genai import types

client = genai.Client(
    api_key="<local-proxy-api-key>",
    http_options=types.HttpOptions(base_url="http://localhost:8090"),
)
response = client.models.generate_content(
    model="GigaChat-2-Max",
    contents="Briefly explain SSE",
)
print(response.text)
```

To select a GigaChat backend contract for Gemini, include `/v1` or `/v2` in
the operation URL or use the corresponding integration configuration. See the
[Gemini examples](https://github.com/ai-forever/gpt2giga/tree/main/examples/gemini)
for streaming, tools, structured output, token counting, and embeddings.

## Per-request GigaChat authorization

If a client must pass GigaChat authorization via `Authorization`, enable:

```dotenv
GPT2GIGA_PASS_TOKEN=True
```

Supported header values:

- `giga-cred-<credentials>:<scope>` for GigaChat authorization key credentials;
- `giga-auth-<access_token>` for a ready access token;
- `giga-user-<user>:<password>` for username/password authorization.

For typical deployment scenarios, server-side `GIGACHAT_*` credentials are preferable. Enable `GPT2GIGA_PASS_TOKEN=True` only if you need client-specific upstream credentials.

## Examples

- OpenAI Chat Completions: [examples/openai/chat_completions/README.md](https://github.com/ai-forever/gpt2giga/blob/main/examples/openai/chat_completions/README.md)
- OpenAI Responses: [examples/openai/responses/README.md](https://github.com/ai-forever/gpt2giga/blob/main/examples/openai/responses/README.md)
- Anthropic Messages: [examples/anthropic/README.md](https://github.com/ai-forever/gpt2giga/blob/main/examples/anthropic/README.md)
- Gemini GenerateContent: [examples/gemini/README.md](https://github.com/ai-forever/gpt2giga/blob/main/examples/gemini/README.md)
- All examples: [examples/README.md](https://github.com/ai-forever/gpt2giga/blob/main/examples/README.md)
