# Gemini Developer API через `gpt2giga`

`gpt2giga` поддерживает Gemini Developer API-совместимые эндпоинты под префиксом `/v1beta`. Это позволяет использовать официальный Python SDK [`google-genai`](https://github.com/googleapis/python-genai) поверх локального прокси.

## Зависимости

Gemini-примеры находятся в группе `integrations`:

```bash
uv sync --group integrations
```

## Базовая настройка

Во всех примерах используется:

- `api_key="0"` как заглушка;
- `http_options=types.HttpOptions(base_url="http://localhost:8090")`.

Если у вас включена защита API-ключом (`GPT2GIGA_ENABLE_API_KEY_AUTH=True`), подставьте ваш ключ вместо `"0"`.

## Запуск

```bash
uv run python examples/gemini/content/generate_content.py
uv run python examples/gemini/content/stream_generate_content.py
uv run python examples/gemini/content/chat.py
uv run python examples/gemini/count_tokens/count_tokens.py
uv run python examples/gemini/files/files.py
uv run python examples/gemini/batches/batches.py
uv run python examples/gemini/embeddings/embeddings.py
```

## Структура по capability

| Capability | Каталог | Что внутри |
|---|---|---|
| content generation | [content/README.md](./content/README.md) | `generate_content`, stream, chat-session, function calling, structured output |
| `countTokens` | [count_tokens/README.md](./count_tokens/README.md) | Подсчёт токенов для `models.count_tokens(...)` |
| files | [files/README.md](./files/README.md) | Upload, list, get, download, delete |
| batches | [batches/README.md](./batches/README.md) | `batchGenerateContent` и bundled JSONL source |
| embeddings | [embeddings/README.md](./embeddings/README.md) | `models.embed_content(...)` с несколькими строками |

## Нюансы

- Генерация использует реальные GigaChat model ids, например `GigaChat-2-Max`.
- Эмбеддинги используют модель, настроенную на стороне proxy. По умолчанию это `EmbeddingsGigaR`; если вы поменяли `GPT2GIGA_EMBEDDINGS`, обновите `model=...` в примере.
- `embeddings/embeddings.py` передаёт список `contents=[...]`, поэтому пример покрывает batch-style embeddings flow поверх Gemini-compatible embeddings routes.
- Совместимость в этой итерации сфокусирована на text, function calling, files, batchGenerateContent и embeddings.
- Built-in Gemini tools и часть мультимодальных/file-backed сценариев всё ещё остаются вне scope.
