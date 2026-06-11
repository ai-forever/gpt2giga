# Развертывание

Docker Compose manifests лежат в [deploy/](../deploy/). Они используют корневой `.env` и build context из корня репозитория.

## Карта Compose-файлов

| Файл | Назначение |
|---|---|
| [deploy/base.yaml](../deploy/base.yaml) | Базовый gpt2giga service с профилями `DEV` и `PROD`. |
| [deploy/traefik.yaml](../deploy/traefik.yaml) | Traefik и несколько gpt2giga instances для примера model-based routing. |
| [deploy/nginx.yaml](../deploy/nginx.yaml) | Минимальный nginx reverse-proxy compose stack. |
| [deploy/observability.yaml](../deploy/observability.yaml) | gpt2giga с mitmproxy для отладки traffic. |
| [deploy/observe-multiple.yaml](../deploy/observe-multiple.yaml) | Несколько gpt2giga instances за mitmproxy. |
| [deploy/mitmproxy.yaml](../deploy/mitmproxy.yaml) | Optional mitmproxy overlay для `base.yaml`, Phoenix и других compose overlays. |
| [deploy/postgres.yaml](../deploy/postgres.yaml) | Optional Postgres durable traffic-log backend. |
| [deploy/opensearch.yaml](../deploy/opensearch.yaml) | Optional OpenSearch traffic-log mirror. |
| [deploy/phoenix.yaml](../deploy/phoenix.yaml) | Optional Phoenix/OpenTelemetry observability stack. |

Команды для копирования есть в [deploy/README.md](../deploy/README.md).

## Базовый service

DEV:

```sh
docker compose --env-file .env -f deploy/base.yaml --profile DEV up -d
```

PROD:

```sh
docker compose --env-file .env -f deploy/base.yaml --profile PROD up -d
```

`PROD` profile по умолчанию привязывает service к `127.0.0.1:${GPT2GIGA_PORT:-8090}`. Для внешнего traffic используйте reverse proxy или осознанно меняйте `ports:`.

## Минимум для production

Перед внешним доступом задайте:

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

`PROD` mode отключает `/docs`, `/redoc`, `/openapi.json`, `/logs`, `/logs/stream`, `/logs/html` и требует `GPT2GIGA_API_KEY`.

## Reverse proxy и TLS

Используйте nginx, Caddy, Traefik или другой reverse proxy для TLS termination, rate limiting и perimeter controls.

Пример Traefik:

```sh
docker compose --env-file .env -f deploy/traefik.yaml up -d
```

Пример Traefik использует host-based routing из [traefik/rules.yml](../traefik/rules.yml). Если обращаетесь по IP, задайте `HOST=127.0.0.1` или отправляйте ожидаемый `Host` header.

Локальный self-signed HTTPS можно включить прямо в app:

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

Для production лучше использовать reverse proxy или managed ingress с реальными сертификатами.

## Optional traffic-log backends

Durable storage в Postgres:

```sh
docker compose --env-file .env \
  -f deploy/base.yaml -f deploy/postgres.yaml \
  --profile DEV --profile postgres up -d --build
```

Postgres по умолчанию доступен на `127.0.0.1:${GPT2GIGA_POSTGRES_PORT:-5432}`. Перед shared use задайте сильный `GPT2GIGA_POSTGRES_PASSWORD`.

OpenSearch mirror поверх Postgres:

```sh
docker compose --env-file .env \
  -f deploy/base.yaml -f deploy/postgres.yaml -f deploy/opensearch.yaml \
  --profile DEV --profile postgres --profile opensearch up -d --build
```

OpenSearch — optional search/index mirror. Durable source of truth остаётся Postgres.

## Phoenix observability

```sh
docker compose --env-file .env \
  -f deploy/base.yaml -f deploy/phoenix.yaml \
  --profile DEV --profile phoenix up -d --build
```

Phoenix UI доступен на `http://localhost:${PHOENIX_PORT:-6006}`. OTLP gRPC collector доступен на `127.0.0.1:${PHOENIX_GRPC_PORT:-4317}`.

Payload capture остаётся выключенным, пока вы явно не включите соответствующие observability capture flags.

## Phoenix + mitmproxy

Для одновременного Phoenix tracing и перехвата исходящего GigaChat traffic:

```sh
docker compose --env-file .env \
  -f deploy/base.yaml -f deploy/phoenix.yaml -f deploy/mitmproxy.yaml \
  --profile DEV --profile phoenix --profile mitmproxy up -d --build
```

То же через Makefile:

```sh
make phoenix-mitm-dev-d
```

mitmproxy UI доступен на `http://localhost:${MITMPROXY_WEB_PORT:-8081}`. Proxy port по умолчанию привязан к `127.0.0.1:${MITMPROXY_PORT:-8080}`.

## Checklist для production hardening

- Установите `GPT2GIGA_MODE=PROD`.
- Установите `GPT2GIGA_ENABLE_API_KEY_AUTH=True` и сильный `GPT2GIGA_API_KEY`.
- Держите `GIGACHAT_VERIFY_SSL_CERTS=True`.
- Завершайте TLS на reverse proxy или включайте app HTTPS с реальными сертификатами.
- Ограничьте `GPT2GIGA_CORS_ALLOW_ORIGINS` известными доменами.
- Храните секреты в environment variables, `.env` или secrets manager.
- Не передавайте секреты через CLI flags.
- Не используйте `GPT2GIGA_LOG_LEVEL=DEBUG` в production.
- Держите content capture выключенным, пока не утверждены redaction, retention и access policies.
- Используйте network isolation вокруг proxy и storage backends.
- Мониторьте `/health`, `/ping` и optional `/metrics`.
