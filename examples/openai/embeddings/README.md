# OpenAI Embeddings API через `gpt2giga`

Эта папка содержит runnable-пример для OpenAI Embeddings API (`/embeddings` или `/v1/embeddings`).

## Базовая настройка

В примере используется:

- `OpenAI(base_url="http://localhost:8090", api_key="0")`
- `model="EmbeddingsGigaR"` как дефолтная embeddings-модель proxy

Если вы поменяли embeddings-модель через `GPT2GIGA_EMBEDDINGS`, обновите `model_name` в примере.

## Быстрый старт

1. Запустите прокси `gpt2giga`.
2. Запустите пример:

```bash
uv run python examples/openai/embeddings/embeddings.py
```

## Что показывает пример

- отправку нескольких строк в одном запросе;
- получение OpenAI-совместимого ответа `client.embeddings.create(...)`;
- вывод первых координат embedding vector для каждой строки.
