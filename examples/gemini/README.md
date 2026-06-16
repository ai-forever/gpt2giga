# Gemini Developer API через `gpt2giga`

`gpt2giga` поддерживает Gemini Developer API-совместимые эндпоинты. Это
позволяет использовать официальный Python SDK
[`google-genai`](https://github.com/googleapis/python-genai) поверх локального
прокси.

Это Gemini-compatible examples, а не полный Gemini API clone. Runnable examples
покрывают text generation, streaming, chat session, function calling,
structured output, `countTokens` и text embeddings. Files/Batches examples
показывают подготовленный client flow, но соответствующие public routes в
обычном app пока не смонтированы.

## Зависимости

Gemini-примеры находятся в группе `integrations`:

```bash
uv sync --group integrations
```

## Базовая настройка

Во всех примерах используется:

- `api_key="0"` как заглушка;
- `http_options=types.HttpOptions(base_url="http://localhost:8090", ...)`
  с `api_version=api_version`.

```python
api_version = "v1"
client = genai.Client(
    api_key="0",
    http_options=types.HttpOptions(
        base_url="http://localhost:8090",
        api_version=api_version,
    ),
)
```

Если у вас включена защита API-ключом (`GPT2GIGA_ENABLE_API_KEY_AUTH=True`),
подставьте ваш ключ вместо `"0"`.

Gemini operation routes доступны в корне, под `/v1`, `/v2` и `/v1beta`.
Официальный `google-genai` SDK при таком `base_url` ходит в Gemini-compatible
маршруты через свой обычный `/v1beta` path. Если клиент добавляет `/v1beta`
к versioned base URL, `gpt2giga` также принимает `/v1/v1beta/...` и
`/v2/v1beta/...`.

## Версия API

Выбор версии GigaChat API для Gemini-примеров задаётся в `types.HttpOptions`.
Укажите `api_version="v1"`, чтобы SDK ходил в `/v1`, или `api_version="v2"`,
чтобы SDK ходил в `/v2`:

```python
api_version = "v1"
client = genai.Client(
    api_key="0",
    http_options=types.HttpOptions(
        base_url="http://localhost:8090",
        api_version=api_version,
    ),
)
```

Если `api_version` не указан, `google-genai` использует свой обычный Gemini
path, а `gpt2giga` выбирает backend mode по
`GPT2GIGA_GIGACHAT_API_MODE=v1|v2`. Иначе `api_version="v1"` всегда идёт в
GigaChat v1 contract, а `api_version="v2"` — в GigaChat v2 contract.
Для клиентов вроде Gemini CLI можно указать `base_url="http://localhost:8090/v2"`:
их `/v1beta/...` path будет обработан как `/v2/v1beta/...` и выполнен через
GigaChat v2 contract.

## Запуск

```bash
uv run python examples/gemini/content/generate_content.py
uv run python examples/gemini/content/stream_generate_content.py
uv run python examples/gemini/content/chat.py
uv run python examples/gemini/count_tokens/count_tokens.py
uv run python examples/gemini/embeddings/embeddings.py
```

Prepared Files/Batches examples are included for the implemented router modules,
but those routes are not mounted by the default public app yet:

```bash
uv run python examples/gemini/files/files.py
uv run python examples/gemini/batches/batches.py
```

## Структура по capability

| Capability | Каталог | Что внутри |
|---|---|---|
| content generation | [content/README.md](./content/README.md) | `generate_content`, stream, chat-session, function calling, structured output |
| `countTokens` | [count_tokens/README.md](./count_tokens/README.md) | Подсчёт токенов для `models.count_tokens(...)` |
| files | [files/README.md](./files/README.md) | Prepared upload, list, get, download, delete |
| batches | [batches/README.md](./batches/README.md) | Prepared `batchGenerateContent` и bundled JSONL source |
| embeddings | [embeddings/README.md](./embeddings/README.md) | `models.embed_content(...)` с несколькими строками |

## Нюансы

- Генерация использует реальные GigaChat model ids, например `GigaChat-2-Max`.
- Эмбеддинги используют модель, настроенную на стороне proxy. По умолчанию это
  `EmbeddingsGigaR`; если вы поменяли `GPT2GIGA_EMBEDDINGS`, обновите
  `model=...` в примере.
- `embeddings/embeddings.py` передаёт список `contents=[...]`, поэтому пример
  покрывает batch-style embeddings flow поверх Gemini-compatible embeddings
  routes.
- Совместимость в этой итерации сфокусирована на text, function calling,
  embeddings и подготовленных files/batchGenerateContent handlers.
- Built-in Gemini tools, safety enforcement, `cachedContent`, non-text
  embeddings content и часть мультимодальных/file-backed сценариев всё ещё
  остаются вне scope.
- `countTokens` использует GigaChat token counting по извлеченному тексту и
  является compatibility approximation, а не точным Gemini tokenizer.
