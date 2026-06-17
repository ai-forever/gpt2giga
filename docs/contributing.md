# Документация

Этот сайт собирается из Markdown-файлов в `docs/` через MkDocs Material и публикуется на GitHub Pages.

## Локальная сборка

Установите зависимости проекта и docs-группы:

```sh
uv sync --all-extras --dev --group docs
```

Соберите сайт:

```sh
uv run --group docs mkdocs build --strict
```

Для локального предпросмотра:

```sh
uv run --group docs mkdocs serve
```

По умолчанию MkDocs откроет сайт на `http://127.0.0.1:8000/`.
Если порт занят, задайте другой адрес:

```sh
uv run --group docs mkdocs serve -a 127.0.0.1:8001
```

## Что публикуется

Публичный сайт включает:

- пользовательские guides из `docs/*.md`;
- architecture notes из `docs/architecture/`;
- ссылки на runnable examples и integration guides в репозитории;
- GitHub links на deployment manifests и другие файлы вне `docs/`.

## Правила обновления

- Держите README и `mkdocs.yml` согласованными по списку основных документов.
- Для ссылок на файлы вне `docs/` используйте GitHub URLs, иначе опубликованный сайт может вести за пределы Pages artifact.
- Не публикуйте secrets, локальные `.env`, credentials, keys или raw traffic payloads.
- При изменении deployment behavior обновляйте одновременно `docs/deployment.md`, `deploy/README.md` и relevant compose manifests.
- При изменении compatibility behavior обновляйте `docs/api-compatibility.md` и `docs/client-parameter-compatibility.md`.
