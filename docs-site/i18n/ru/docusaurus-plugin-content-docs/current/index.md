# Документация gpt2giga

`gpt2giga` — это шлюз совместимости на FastAPI, который принимает запросы в форматах OpenAI, Anthropic и Gemini и перенаправляет их в GigaChat. Он нужен, когда клиент, редактор, агентный фреймворк или SDK умеет работать с API OpenAI/Anthropic/Gemini, а в роли реального бэкенда должен выступать GigaChat.

Локальный адрес по умолчанию:

```text
http://localhost:8090
```

## Что закрывает прокси

| Возможность | Где читать |
|---|---|
| Быстрый запуск через Docker Compose или `uv` | [Быстрый старт](quickstart.md) |
| Поддерживаемые маршруты OpenAI, Anthropic, Gemini и LiteLLM | [Совместимость API](api-compatibility.md) |
| Поведение `extra_headers`, `extra_query`, `extra_body` и необязательных полей | [Параметры клиентов](client-parameter-compatibility.md) |
| Встроенные инструменты GigaChat и их сопоставление с OpenAI/Anthropic/Gemini | [Встроенные инструменты](builtin-tools.md) |
| Переменные окружения, аутентификация, лимиты, метрики, наблюдаемость | [Конфигурация](configuration.md) |
| Профили Compose, Traefik, nginx, Postgres, OpenSearch, Phoenix | [Развёртывание](deployment.md) |
| Журналы выполнения, журналы трафика, admin API, отладочная трансляция | [Операции](operations.md) |
| Настройка редакторов, агентов, SDK и обратного прокси | [Интеграции](integrations.md) |

## Текущий набор API

Публичные маршруты доступны в корне и под версионированными префиксами:

- `/chat/completions`, `/v1/chat/completions`, `/v2/chat/completions`
- `/responses`, `/v1/responses`, `/v2/responses`
- `/embeddings`, `/v1/embeddings`, `/v2/embeddings`
- `/messages`, `/v1/messages`, `/v2/messages`
- `/v1beta/models/{model}:generateContent` и совместимые пути Gemini
- `/models`, `/model/info`, `/health`, `/ping`

Правило выбора бэкенда одинаково для маршрутов, совместимых с OpenAI, Anthropic
и Gemini: `/v1/...` всегда отправляет чат-подобные запросы в контракт
GigaChat v1, `/v2/...` — в контракт GigaChat v2, а корневой путь без `/v1`
или `/v2` использует `GPT2GIGA_GIGACHAT_API_MODE=v1|v2`.

OpenAI Files/Batches, Anthropic Message Batches и Gemini Files/Batches подготовлены в коде, но намеренно не подключены до появления сквозного (end-to-end) выполнения в SDK или бэкенде вышестоящего сервиса.

## Быстрый путь

1. Скопируйте `.env.example` в `.env`.
2. Заполните `GIGACHAT_CREDENTIALS`, `GIGACHAT_SCOPE`, `GIGACHAT_MODEL`.
3. Запустите `docker compose --env-file .env -f deploy/base.yaml --profile DEV up -d`.
4. Проверьте `curl http://localhost:8090/health`.
5. Подключите SDK к `http://localhost:8090/v1` или `http://localhost:8090/v2` для явного контракта бэкенда, либо к `http://localhost:8090`, если корень должен следовать `GPT2GIGA_GIGACHAT_API_MODE`.

## Для разработчиков

- [Нормализованные сообщения](architecture/normalized-messages.md) описывают экспериментальный слой моделей, не зависящих от протокола.
- [Логирование и наблюдаемость](architecture/logging-and-observability.md) фиксирует границы между журналами выполнения, журналами трафика, метриками и трейсами.
- [Добавление провайдера или протокола](architecture/how-to-add-provider.md) даёт чек-лист для расширения набора публичных протоколов и вышестоящих провайдеров.
