# Quickstart

This document helps you quickly launch an OpenAI/Anthropic-compatible proxy to GigaChat.

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

## Local run

Install as a tool:

```sh
uv tool install gpt2giga
gpt2giga
```

Or run from the repository:

```sh
uv sync --all-extras --dev
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
- All examples: [examples/README.md](https://github.com/ai-forever/gpt2giga/blob/main/examples/README.md)
