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

## Фиксация версий

Для удобного ознакомления примеры используют
`ghcr.io/ai-forever/gpt2giga:latest`. В production замените `latest` на
проверенный release tag или неизменяемый digest и зафиксируйте версии сторонних
образов. Храните ссылки на образы рядом с Compose-файлами в системе контроля
версий.

Перед развёртыванием зафиксируйте tag и digest gateway, активные Compose-файлы
и профили, состояние backup Postgres и предыдущий рабочий образ.
`docker compose config` раскрывает секреты, поэтому не прикладывайте его
необработанный вывод к задачам или CI-артефактам.

## Обновление

Для базового развёртывания:

```sh
docker compose --env-file .env -f deploy/base.yaml pull
docker compose --env-file .env -f deploy/base.yaml --profile PROD up -d
docker compose --env-file .env -f deploy/base.yaml --profile PROD ps
curl --fail http://127.0.0.1:8090/health
```

Для overlays повторите полный набор `-f` и `--profile`. Не используйте
`down -v` при обновлении: `-v` удаляет именованные volumes.

Init-скрипты Postgres запускаются автоматически только при создании нового
volume. Для существующего volume сначала сделайте backup, затем явно примените
поставляемую идемпотентную миграцию traffic logs:

```sh
docker compose --env-file .env \
  -f deploy/base.yaml -f deploy/postgres.yaml \
  --profile PROD --profile postgres \
  exec -T postgres sh /docker-entrypoint-initdb.d/001_apply_traffic_log_migration.sh
```

После обновления проверьте `/health`, один аутентифицированный запрос модели,
streaming, tool calling (если используется) и все storage/telemetry sinks. До
увеличения трафика проверьте логи на ошибки редактирования и повторяющиеся
upstream failures.

## Резервное копирование и восстановление

Перед обновлением схемы или образа сохраните traffic logs из Postgres:

```sh
docker compose --env-file .env \
  -f deploy/base.yaml -f deploy/postgres.yaml \
  --profile PROD --profile postgres \
  exec -T postgres sh -c \
  'pg_dump --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" --format=custom' \
  > gpt2giga-traffic-logs.dump
```

Команда читает имена БД и пользователя внутри контейнера; одинарные кавычки
намеренно блокируют подстановку host shell. Dump может содержать content модели:
шифруйте его, ограничивайте доступ и применяйте retention policy исходной БД.

Сначала восстановите backup в пустую изолированную БД и проверьте её:

```sh
docker compose --env-file .env \
  -f deploy/base.yaml -f deploy/postgres.yaml \
  --profile PROD --profile postgres \
  exec -T postgres sh -c \
  'pg_restore --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" --clean --if-exists' \
  < gpt2giga-traffic-logs.dump
```

Legacy-данные других продуктов не входят в манифесты gateway. Перед изменением
или удалением данных вынесенного продукта следуйте отдельным
[инструкциям по миграции и legacy](gigaloom-migration.md).

## Откат

1. Прекратите направлять новый трафик на instance и сохраните отредактированную
   диагностику.
2. Верните предыдущую зафиксированную ссылку на образ gateway.
3. Запустите те же overlays и profiles без удаления volumes.
4. Восстанавливайте Postgres только после несовместимого изменения данных; при
   совместимой схеме безопаснее откатить только бинарную версию.
5. Проверьте health и минимальный аутентифицированный запрос до возврата трафика.

Если инцидент связан с утечкой credentials или небезопасным content capture,
смените ключи и изолируйте артефакты, а не только запускайте старый образ.

## Диагностика после запуска

```sh
docker compose --env-file .env -f deploy/base.yaml --profile PROD ps
docker compose --env-file .env -f deploy/base.yaml --profile PROD logs --tail 200 gpt2giga-prod
curl --fail http://127.0.0.1:8090/health
curl --fail -H "Authorization: Bearer <proxy-api-key>" http://127.0.0.1:8090/v1/models
```

Метрики, traffic logs, admin-диагностика и разница между runtime logs и
захваченным content модели описаны в [Operations](./operations.md).

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
