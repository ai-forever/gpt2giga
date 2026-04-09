# OpenAI Files API через `gpt2giga`

Эта папка содержит runnable-пример для OpenAI Files API (`/files`).

## Быстрый старт

1. Запустите прокси `gpt2giga`.
2. Запустите пример:

```bash
uv run python examples/openai/files/files.py
```

## Что показывает пример

- загрузку файла с `purpose="batch"`;
- чтение metadata;
- получение содержимого файла;
- удаление загруженного файла.
