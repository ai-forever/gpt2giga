# Развёртывание

Манифесты Docker Compose лежат в [deploy/](https://github.com/ai-forever/gpt2giga/tree/main/deploy). Они используют корневой `.env` и контекст сборки из корня репозитория.

## Карта Compose-файлов

| Файл | Назначение |
|---|---|
| [deploy/base.yaml](https://github.com/ai-forever/gpt2giga/blob/main/deploy/base.yaml) | Базовый сервис gpt2giga с профилями `DEV` и `PROD`. |
| [deploy/traefik.yaml](https://github.com/ai-forever/gpt2giga/blob/main/deploy/traefik.yaml) | Traefik и несколько экземпляров gpt2giga для примера маршрутизации по модели. |
| [deploy/nginx.yaml](https://github.com/ai-forever/gpt2giga/blob/main/deploy/nginx.yaml) | Минимальный compose-стек с nginx в роли обратного прокси. |
| [deploy/observability.yaml](https://github.com/ai-forever/gpt2giga/blob/main/deploy/observability.yaml) | gpt2giga с mitmproxy для отладки трафика. |
| [deploy/observe-multiple.yaml](https://github.com/ai-forever/gpt2giga/blob/main/deploy/observe-multiple.yaml) | Несколько экземпляров gpt2giga за mitmproxy. |
| [deploy/mitmproxy.yaml](https://github.com/ai-forever/gpt2giga/blob/main/deploy/mitmproxy.yaml) | Необязательное наложение mitmproxy для `base.yaml`, Phoenix и других наложений compose. |
| [deploy/postgres.yaml](https://github.com/ai-forever/gpt2giga/blob/main/deploy/postgres.yaml) | Необязательный надёжный бэкенд журналов трафика на Postgres. |
| [deploy/opensearch.yaml](https://github.com/ai-forever/gpt2giga/blob/main/deploy/opensearch.yaml) | Необязательное зеркало журналов трафика на OpenSearch. |
| [deploy/phoenix.yaml](https://github.com/ai-forever/gpt2giga/blob/main/deploy/phoenix.yaml) | Необязательный стек наблюдаемости Phoenix/OpenTelemetry. |

Команды для копирования есть в [deploy/README.md](https://github.com/ai-forever/gpt2giga/blob/main/deploy/README.md).

## Базовый сервис

DEV:

```sh
docker compose --env-file .env -f deploy/base.yaml --profile DEV up -d
```

PROD:

```sh
docker compose --env-file .env -f deploy/base.yaml --profile PROD up -d
```

Профиль `PROD` по умолчанию привязывает сервис к `127.0.0.1:${GPT2GIGA_PORT:-8090}`. Для внешнего трафика используйте обратный прокси или осознанно меняйте `ports:`.

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

Режим `PROD` отключает `/docs`, `/redoc`, `/openapi.json`, `/logs`, `/logs/stream`, `/logs/html` и требует `GPT2GIGA_API_KEY`.

## Обратный прокси и TLS

Используйте nginx, Caddy, Traefik или другой обратный прокси для терминации TLS, ограничения частоты запросов и контроля периметра.

Пример Traefik:

```sh
docker compose --env-file .env -f deploy/traefik.yaml up -d
```

Пример Traefik использует маршрутизацию по хосту из [traefik/rules.yml](https://github.com/ai-forever/gpt2giga/blob/main/traefik/rules.yml). Если обращаетесь по IP, задайте `HOST=127.0.0.1` или отправляйте ожидаемый заголовок `Host`.

Локальный HTTPS с самоподписанным сертификатом можно включить прямо в приложении:

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

Для production лучше использовать обратный прокси или управляемый ingress с реальными сертификатами.

## Необязательные бэкенды журналов трафика

Надёжное хранилище в Postgres:

```sh
docker compose --env-file .env \
  -f deploy/base.yaml -f deploy/postgres.yaml \
  --profile DEV --profile postgres up -d --build
```

Postgres по умолчанию доступен на `127.0.0.1:${GPT2GIGA_POSTGRES_PORT:-5432}`. Перед совместным использованием задайте сильный `GPT2GIGA_POSTGRES_PASSWORD`.

Зеркало OpenSearch поверх Postgres:

```sh
docker compose --env-file .env \
  -f deploy/base.yaml -f deploy/postgres.yaml -f deploy/opensearch.yaml \
  --profile DEV --profile postgres --profile opensearch up -d --build
```

OpenSearch — необязательное зеркало для поиска/индексации. Надёжным источником истины остаётся Postgres.

## Наблюдаемость Phoenix

```sh
docker compose --env-file .env \
  -f deploy/base.yaml -f deploy/phoenix.yaml \
  --profile DEV --profile phoenix up -d --build
```

Интерфейс Phoenix доступен на `http://localhost:${PHOENIX_PORT:-6006}`. Коллектор OTLP gRPC доступен на `127.0.0.1:${PHOENIX_GRPC_PORT:-4317}`.

Захват полезной нагрузки остаётся выключенным, пока вы явно не включите соответствующие флаги захвата наблюдаемости.

## Phoenix + mitmproxy

Для одновременной трассировки Phoenix и перехвата исходящего трафика GigaChat:

```sh
docker compose --env-file .env \
  -f deploy/base.yaml -f deploy/phoenix.yaml -f deploy/mitmproxy.yaml \
  --profile DEV --profile phoenix --profile mitmproxy up -d --build
```

То же через Makefile:

```sh
make phoenix-mitm-dev-d
```

Интерфейс mitmproxy доступен на `http://localhost:${MITMPROXY_WEB_PORT:-8081}`. Порт прокси по умолчанию привязан к `127.0.0.1:${MITMPROXY_PORT:-8080}`.

## Чек-лист усиления безопасности для production

- Установите `GPT2GIGA_MODE=PROD`.
- Установите `GPT2GIGA_ENABLE_API_KEY_AUTH=True` и сильный `GPT2GIGA_API_KEY`.
- Держите `GIGACHAT_VERIFY_SSL_CERTS=True`.
- Завершайте TLS на обратном прокси или включайте HTTPS приложения с реальными сертификатами.
- Ограничьте `GPT2GIGA_CORS_ALLOW_ORIGINS` известными доменами.
- Храните секреты в переменных окружения, `.env` или менеджере секретов.
- Не передавайте секреты через флаги CLI.
- Не используйте `GPT2GIGA_LOG_LEVEL=DEBUG` в production.
- Держите захват содержимого выключенным, пока не утверждены политики маскирования, срока хранения и доступа.
- Используйте сетевую изоляцию вокруг прокси и бэкендов хранилища.
- Мониторьте `/health`, `/ping` и (опционально) `/metrics`.
