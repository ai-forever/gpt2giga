# Deploy Presets

В `deploy/` лежат готовые примеры для локального запуска, отладки и более
сложных compose-сценариев.

## Перед стартом

1. Создайте `.env` в корне репозитория:

   ```bash
   cp .env.example .env
   ```

2. Заполните минимум:

   ```dotenv
   GIGACHAT_CREDENTIALS=...
   GIGACHAT_SCOPE=GIGACHAT_API_PERS
   GPT2GIGA_API_KEY=...
   ```

   Если upstream TLS использует корпоративный или self-signed CA, добавьте:

   ```dotenv
   GIGACHAT_CA_BUNDLE_FILE=/certs/company-root.pem
   GIGACHAT_VERIFY_SSL_CERTS=True
   ```

   И смонтируйте PEM bundle в контейнер по тому же пути через bind mount или свой compose override.

3. Все команды ниже запускаются из корня репозитория через `make`.

`Makefile` автоматически передает `.env` в `docker compose --env-file .env`, а основные compose-пресеты дополнительно подключают этот же файл как container `env_file`, чтобы `GIGACHAT_*`/`GPT2GIGA_*` были доступны внутри `gpt2giga`.

## Что запускать

| Сценарий | Файл(ы) | Команда | Что поднимается |
|---|---|---|---|
| Один инстанс, `DEV` | `deploy/compose/base.yaml` | `make compose-base-dev-d` | Один `gpt2giga`, `/docs`, `/admin`, порт `8090` |
| Один инстанс, `PROD` | `deploy/compose/base.yaml` | `make compose-base-prod-d` | Один `gpt2giga` в `PROD`, порт `8090` только на `127.0.0.1` |
| Отладка через mitmproxy | `deploy/compose/observability.yaml` | `make compose-observe-dev-d` | `gpt2giga` + `mitmproxy`/`mitmweb`, порты `8090`, `8080`, `8081` |
| Несколько моделей | `deploy/compose/multiple.yaml` | `make compose-multiple-up-d` | Два инстанса: `8090` и `8091` |
| Несколько моделей + mitmproxy | `deploy/compose/observe-multiple.yaml` | `make compose-observe-multiple-up-d` | Три инстанса + `mitmproxy`, порты `8090-8092`, `8080`, `8081` |
| Несколько инстансов за Traefik | `deploy/compose/traefik.yaml` | `make compose-traefik-up-d` | `gpt2giga`, `gpt2giga-pro`, `gpt2giga-max`, `traefik` |
| Base + Prometheus | `deploy/compose/base.yaml` + `deploy/compose/observability-prometheus.yaml` | `make compose-prometheus-dev-d` | `gpt2giga` + Prometheus на `9090` |
| Base + OTLP collector | `deploy/compose/base.yaml` + `deploy/compose/observability-otlp.yaml` | `make compose-otlp-dev-d` | `gpt2giga` + OpenTelemetry Collector |
| Base + Langfuse | `deploy/compose/base.yaml` + `deploy/compose/observability-langfuse.yaml` | `make compose-langfuse-dev-d` | `gpt2giga` + Langfuse + Postgres + ClickHouse + Redis + MinIO |
| Base + Phoenix | `deploy/compose/base.yaml` + `deploy/compose/observability-phoenix.yaml` | `make compose-phoenix-dev-d` | `gpt2giga` + self-hosted Phoenix на `6006` |
| Runtime backend: Redis | `deploy/compose/runtime-backends/redis.yaml` | `make compose-runtime-redis-up-d` | `gpt2giga` + Redis |
| Runtime backend: Postgres | `deploy/compose/runtime-backends/postgres.yaml` | `make compose-runtime-postgres-up-d` | `gpt2giga` + Postgres |
| Runtime backend: S3/MinIO | `deploy/compose/runtime-backends/s3.yaml` | `make compose-runtime-s3-up-d` | `gpt2giga` + MinIO |
| Локальный nginx example | `deploy/compose/nginx.yaml` | `make compose-nginx-up-d` | Пример app + nginx для локальной сборки |

Для остановки используйте соответствующий `*-down`, например:

```bash
make compose-base-down
make compose-prometheus-down
make compose-runtime-redis-down
```

## Рекомендованные сценарии

### Просто поднять proxy локально

```bash
make compose-base-dev-d
```

Открывайте:

- `http://localhost:8090/docs`
- `http://localhost:8090/admin`

### Посмотреть метрики в Prometheus

В `.env` задайте sink:

```dotenv
GPT2GIGA_OBSERVABILITY_SINKS=prometheus
```

Запуск:

```bash
make compose-prometheus-dev-d
```

Открывайте:

- `http://localhost:8090/metrics`
- `http://localhost:9090`

### Посмотреть трейсы через OTLP collector

В `.env` задайте sink:

```dotenv
GPT2GIGA_OBSERVABILITY_SINKS=otlp
```

Запуск:

```bash
make compose-otlp-dev-d
```

Collector поднимается на `4317/4318`, debug metrics по умолчанию на `8888`.

### Локально включить Langfuse

В `.env` задайте sink:

```dotenv
GPT2GIGA_OBSERVABILITY_SINKS=langfuse
```

Запуск:

```bash
make compose-langfuse-dev-d
```

После старта:

- `gpt2giga`: `http://localhost:8090`
- `Langfuse UI`: `http://localhost:3000`
- `MinIO API`: `http://localhost:9000`
- `MinIO Console`: `http://localhost:9091`

`observability-langfuse.yaml` использует локальные dev credentials по умолчанию.
Для staging/production их нужно переопределить в `.env`.

### Локально включить Phoenix

В `.env` задайте sink:

```dotenv
GPT2GIGA_OBSERVABILITY_SINKS=phoenix
```

Запуск:

```bash
make compose-phoenix-dev-d
```

После старта:

- `gpt2giga`: `http://localhost:8090`
- `Phoenix UI`: `http://localhost:6006`

`observability-phoenix.yaml` использует self-hosted Phoenix без auth по умолчанию.
Если включаете `PHOENIX_ENABLE_AUTH=true`, после первого входа создайте system API key в Phoenix UI и задайте его как `GPT2GIGA_PHOENIX_API_KEY`, чтобы `gpt2giga` продолжил отправлять traces.

### Отладить SSE и upstream traffic

```bash
make compose-observe-dev-d
```

После старта:

- `gpt2giga`: `http://localhost:8090`
- proxy: `http://localhost:8080`
- `mitmweb`: `http://localhost:8081`

### Поднять несколько моделей одновременно

```bash
make compose-multiple-up-d
```

По умолчанию:

- `http://localhost:8090` -> `GigaChat-2-Max`
- `http://localhost:8091` -> `GigaChat-3-Ultra`

`traefik.yaml` нужен, если хотите разруливать несколько инстансов через один
reverse proxy.

## Runtime backend examples

Файлы в `deploy/compose/runtime-backends/` только поднимают внешнюю
инфраструктуру и выставляют рекомендованные env-переменные.

Важно:

- они не добавляют реализацию backend-а в код автоматически;
- `GPT2GIGA_RUNTIME_STORE_BACKEND` должен совпадать с именем backend-а,
  зарегистрированного у вас в приложении или плагине;
- если backend-а с таким именем нет, `gpt2giga` не стартует корректно.

Подробности: [runtime-backends/README.md](./compose/runtime-backends/README.md).

## Замечания по отдельным файлам

- `deploy/compose/nginx.yaml` монтирует `../../nginx.conf` в контейнер `nginx`.
  Если такого файла у вас нет, используйте
  [docs/integrations/nginx/README.md](../docs/integrations/nginx/README.md)
  как основной production-гайд.
- `deploy/compose/traefik.yaml` использует конфиги из `deploy/traefik/`.
- Все override-файлы observability рассчитаны на совместный запуск с
  `deploy/compose/base.yaml`, поэтому для них в `Makefile` добавлены отдельные
  комбинированные цели.

## Быстрый список целей

```bash
make help
```
