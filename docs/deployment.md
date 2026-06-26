# Deployment

The Docker Compose manifests live in [deploy/](https://github.com/ai-forever/gpt2giga/tree/main/deploy). They use the root `.env` and the build context from the repository root.

## Compose file map

| File | Purpose |
|---|---|
| [deploy/base.yaml](https://github.com/ai-forever/gpt2giga/blob/main/deploy/base.yaml) | Base gpt2giga service with the `DEV` and `PROD` profiles. |
| [deploy/traefik.yaml](https://github.com/ai-forever/gpt2giga/blob/main/deploy/traefik.yaml) | Traefik and several gpt2giga instances as an example of model-based routing. |
| [deploy/nginx.yaml](https://github.com/ai-forever/gpt2giga/blob/main/deploy/nginx.yaml) | Minimal Compose stack with nginx as a reverse proxy. |
| [deploy/observability.yaml](https://github.com/ai-forever/gpt2giga/blob/main/deploy/observability.yaml) | gpt2giga with mitmproxy for traffic debugging. |
| [deploy/observe-multiple.yaml](https://github.com/ai-forever/gpt2giga/blob/main/deploy/observe-multiple.yaml) | Several gpt2giga instances behind mitmproxy. |
| [deploy/mitmproxy.yaml](https://github.com/ai-forever/gpt2giga/blob/main/deploy/mitmproxy.yaml) | Optional mitmproxy overlay for `base.yaml`, Phoenix, and other Compose overlays. |
| [deploy/postgres.yaml](https://github.com/ai-forever/gpt2giga/blob/main/deploy/postgres.yaml) | Optional durable Postgres traffic-log backend. |
| [deploy/opensearch.yaml](https://github.com/ai-forever/gpt2giga/blob/main/deploy/opensearch.yaml) | Optional OpenSearch traffic-log mirror. |
| [deploy/phoenix.yaml](https://github.com/ai-forever/gpt2giga/blob/main/deploy/phoenix.yaml) | Optional Phoenix/OpenTelemetry observability stack. |

Copyable commands are in [deploy/README.md](https://github.com/ai-forever/gpt2giga/blob/main/deploy/README.md).

## Base service

DEV:

```sh
docker compose --env-file .env -f deploy/base.yaml --profile DEV up -d
```

PROD:

```sh
docker compose --env-file .env -f deploy/base.yaml --profile PROD up -d
```

The `PROD` profile binds the service to `127.0.0.1:${GPT2GIGA_PORT:-8090}` by default. For external traffic, use a reverse proxy or deliberately change `ports:`.

## Production minimum

Before external access, set:

```dotenv
GPT2GIGA_MODE=PROD
GPT2GIGA_HOST=0.0.0.0
GPT2GIGA_PORT=8090
GPT2GIGA_ENABLE_API_KEY_AUTH=True
GPT2GIGA_API_KEY="<strong-random-secret>"
GIGACHAT_CREDENTIALS="<your-gigachat-credentials>"
GIGACHAT_SCOPE=GIGACHAT_API_PERS
GIGACHAT_MODEL=GigaChat-2-Max
GIGACHAT_VERIFY_SSL_CERTS=True
```

`PROD` mode disables `/docs`, `/redoc`, `/openapi.json`, `/logs`, `/logs/stream`, `/logs/html` and requires `GPT2GIGA_API_KEY`.

## Reverse proxy and TLS

Use nginx, Caddy, Traefik, or another reverse proxy for TLS termination, rate limiting, and perimeter controls.

Traefik example:

```sh
docker compose --env-file .env -f deploy/traefik.yaml up -d
```

The Traefik example uses host-based routing from [traefik/rules.yml](https://github.com/ai-forever/gpt2giga/blob/main/traefik/rules.yml). If you connect by IP, set `HOST=127.0.0.1` or send the expected `Host` header.

A local self-signed HTTPS can be enabled directly in the app:

```sh
openssl req -x509 -nodes -days 365 \
  -newkey rsa:4096 \
  -keyout key.pem \
  -out cert.pem \
  -subj "/CN=localhost" \
  -addext "subjectAltName=DNS:localhost,IP:127.0.0.1"
```

```dotenv
GPT2GIGA_USE_HTTPS=True
GPT2GIGA_HTTPS_KEY_FILE=key.pem
GPT2GIGA_HTTPS_CERT_FILE=cert.pem
```

For production, prefer a reverse proxy or managed ingress with real certificates.

## Optional traffic-log backends

Durable storage in Postgres:

```sh
docker compose --env-file .env \
  -f deploy/base.yaml -f deploy/postgres.yaml \
  --profile DEV --profile postgres up -d --build
```

Postgres is available at `127.0.0.1:${GPT2GIGA_POSTGRES_PORT:-5432}` by default. Before shared use, set a strong `GPT2GIGA_POSTGRES_PASSWORD`.

OpenSearch mirror on top of Postgres:

```sh
docker compose --env-file .env \
  -f deploy/base.yaml -f deploy/postgres.yaml -f deploy/opensearch.yaml \
  --profile DEV --profile postgres --profile opensearch up -d --build
```

OpenSearch is an optional search/index mirror. The durable source of truth remains Postgres.

## Phoenix observability

```sh
docker compose --env-file .env \
  -f deploy/base.yaml -f deploy/phoenix.yaml \
  --profile DEV --profile phoenix up -d --build
```

The Phoenix UI is available at `http://localhost:${PHOENIX_PORT:-6006}`. The OTLP gRPC collector is available at `127.0.0.1:${PHOENIX_GRPC_PORT:-4317}`.

Payload capture stays disabled until you explicitly enable the corresponding observability capture flags.

## Phoenix + mitmproxy

For simultaneous Phoenix tracing and interception of outgoing GigaChat traffic:

```sh
docker compose --env-file .env \
  -f deploy/base.yaml -f deploy/phoenix.yaml -f deploy/mitmproxy.yaml \
  --profile DEV --profile phoenix --profile mitmproxy up -d --build
```

The same via Makefile:

```sh
make phoenix-mitm-dev-d
```

The mitmproxy UI is available at `http://localhost:${MITMPROXY_WEB_PORT:-8081}`. The proxy port is bound to `127.0.0.1:${MITMPROXY_PORT:-8080}` by default.

## Production hardening checklist

- Set `GPT2GIGA_MODE=PROD`.
- Set `GPT2GIGA_ENABLE_API_KEY_AUTH=True` and a strong `GPT2GIGA_API_KEY`.
- Keep `GIGACHAT_VERIFY_SSL_CERTS=True`.
- Terminate TLS at a reverse proxy or enable app HTTPS with real certificates.
- Restrict `GPT2GIGA_CORS_ALLOW_ORIGINS` to known domains.
- Store secrets in environment variables, `.env`, or a secrets manager.
- Do not pass secrets via CLI flags.
- Do not use `GPT2GIGA_LOG_LEVEL=DEBUG` in production.
- Keep content capture disabled until redaction, retention, and access policies are approved.
- Use network isolation around the proxy and storage backends.
- Monitor `/health`, `/ping`, and the optional `/metrics`.
