# Deploy

В этой папке лежат Docker Compose manifests для локального и production-like запуска.

Все команды ниже выполняются из корня репозитория и используют корневой `.env`:

```sh
cp .env.example .env
```

## Файлы

| File | Назначение |
|---|---|
| `base.yaml` | Базовый сервис gpt2giga с профилями `DEV` и `PROD`. |
| `traefik.yaml` | Traefik и несколько инстансов gpt2giga. |
| `nginx.yaml` | Минимальный nginx reverse-proxy stack. |
| `observability.yaml` | gpt2giga с mitmproxy. |
| `observe-multiple.yaml` | Несколько model-specific gpt2giga инстансов с mitmproxy. |
| `mitmproxy.yaml` | Optional mitmproxy overlay для `base.yaml` и других overlays. |
| `postgres.yaml` | Optional Postgres traffic-log backend. |
| `opensearch.yaml` | Optional OpenSearch traffic-log mirror. |
| `phoenix.yaml` | Optional Phoenix/OpenTelemetry observability profile. |

## Базовый Сервис

```sh
docker compose --env-file .env -f deploy/base.yaml --profile DEV up -d
docker compose --env-file .env -f deploy/base.yaml --profile PROD up -d
```

## С Postgres Traffic Logs

```sh
docker compose --env-file .env \
  -f deploy/base.yaml -f deploy/postgres.yaml \
  --profile DEV --profile postgres up -d --build
```

## С Postgres И OpenSearch

```sh
docker compose --env-file .env \
  -f deploy/base.yaml -f deploy/postgres.yaml -f deploy/opensearch.yaml \
  --profile DEV --profile postgres --profile opensearch up -d --build
```

## С Phoenix

```sh
docker compose --env-file .env \
  -f deploy/base.yaml -f deploy/phoenix.yaml \
  --profile DEV --profile phoenix up -d --build
```

То же через Makefile:

```sh
make phoenix-dev-d
```

## С Phoenix И mitmproxy

```sh
docker compose --env-file .env \
  -f deploy/base.yaml -f deploy/phoenix.yaml -f deploy/mitmproxy.yaml \
  --profile DEV --profile phoenix --profile mitmproxy up -d --build
```

То же через Makefile:

```sh
make phoenix-mitm-dev-d
```

## С Traefik

```sh
docker compose --env-file .env -f deploy/traefik.yaml up -d
```

Traefik routing использует `traefik/rules.yml`. Задайте `HOST` в `.env`, если обращаетесь к stack по IP или custom hostname.

## С mitmproxy

```sh
docker compose --env-file .env -f deploy/observability.yaml --profile DEV up -d
```

Для composable запуска поверх `base.yaml` используйте `deploy/mitmproxy.yaml`.

Используйте только для локальной отладки. Не открывайте mitmproxy наружу.

## Подробнее

Production hardening, TLS, reverse proxy и optional storage/observability settings описаны в [docs/deployment.md](../docs/deployment.md).
