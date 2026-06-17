# gpt2giga documentation

`gpt2giga` - FastAPI compatibility gateway, который принимает OpenAI-, Anthropic- и Gemini-shaped запросы и отправляет их в GigaChat. Он нужен, когда клиент, редактор, агентный framework или SDK умеет работать с OpenAI/Anthropic/Gemini API, а реальный backend должен быть GigaChat.

Локальный адрес по умолчанию:

```text
http://localhost:8090
```

## Что закрывает прокси

| Возможность | Где читать |
|---|---|
| Быстрый запуск через Docker Compose или `uv` | [Быстрый старт](quickstart.md) |
| Краткая матрица OpenAI, Anthropic, Gemini и LiteLLM поддержки | [Compatibility matrix](compatibility.md) |
| Поддержанные OpenAI, Anthropic, Gemini и LiteLLM routes | [API compatibility](api-compatibility.md) |
| Поведение `extra_headers`, `extra_query`, `extra_body` и optional fields | [Client parameters](client-parameter-compatibility.md) |
| Встроенные инструменты GigaChat и маппинг OpenAI/Anthropic/Gemini | [Встроенные инструменты](builtin-tools.md) |
| Переменные окружения, auth, limits, metrics, observability | [Конфигурация](configuration.md) |
| Compose profiles, Traefik, nginx, Postgres, OpenSearch, Phoenix | [Развертывание](deployment.md) |
| Runtime logs, traffic logs, admin API, debug translate | [Операции](operations.md) |
| Editor, agent, SDK и reverse-proxy setup | [Интеграции](integrations.md) |

## Текущая API-поверхность

Публичные routes доступны в корне и под versioned prefixes:

- `/chat/completions`, `/v1/chat/completions`, `/v2/chat/completions`
- `/responses`, `/v1/responses`, `/v2/responses`
- `/embeddings`, `/v1/embeddings`, `/v2/embeddings`
- `/messages`, `/v1/messages`, `/v2/messages`
- `/v1beta/models/{model}:generateContent` и совместимые Gemini paths
- `/models`, `/model/info`, `/health`, `/ping`

Правило выбора backend одинаковое для OpenAI-, Anthropic- и Gemini-compatible
routes: `/v1/...` всегда отправляет chat-like запросы в GigaChat v1 contract,
`/v2/...` всегда отправляет их в GigaChat v2 contract, а root path без `/v1`
или `/v2` использует `GPT2GIGA_GIGACHAT_API_MODE=v1|v2`.

OpenAI Files/Batches, Anthropic Message Batches и Gemini Files/Batches подготовлены в коде, но намеренно не смонтированы до появления end-to-end execution в upstream SDK/backend.

## Быстрый путь

1. Скопируйте `.env.example` в `.env`.
2. Заполните `GIGACHAT_CREDENTIALS`, `GIGACHAT_SCOPE`, `GIGACHAT_MODEL`.
3. Запустите `docker compose --env-file .env -f deploy/base.yaml --profile DEV up -d`.
4. Проверьте `curl http://localhost:8090/health`.
5. Подключите SDK к `http://localhost:8090/v1` или `http://localhost:8090/v2` для явного backend contract, либо к `http://localhost:8090`, если root должен следовать `GPT2GIGA_GIGACHAT_API_MODE`.

## Для разработчиков

- [Normalized messages](architecture/normalized-messages.md) описывает экспериментальный слой protocol-independent моделей.
- [Logging и observability](architecture/logging-and-observability.md) фиксирует границы runtime logs, traffic logs, metrics и traces.
- [Добавление provider/protocol](architecture/how-to-add-provider.md) дает checklist для расширения public protocol surface и upstream providers.
