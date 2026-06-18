# Документация

Этот сайт собирается из Markdown-файлов в `docs/` через Docusaurus wrapper в `docs-site/` и публикуется на GitHub Pages.

## Локальная сборка

Установите Node.js `20+`, затем зависимости Docusaurus:

```sh
cd docs-site
npm ci
```

Соберите сайт:

```sh
npm run build
```

Для локального предпросмотра:

```sh
npm run start
```

По умолчанию Docusaurus откроет сайт на `http://127.0.0.1:3000/`.
Для проверки production artifact после сборки:

```sh
npm run serve
```

## Что публикуется

Публичный сайт включает:

- пользовательские guides из `docs/*.md`;
- architecture notes из `docs/architecture/`;
- ссылки на runnable examples и integration guides в репозитории;
- GitHub links на deployment manifests и другие файлы вне `docs/`.

## Правила обновления

- Держите README и `docs-site/sidebars.ts` согласованными по списку основных документов.
- Для ссылок на файлы вне `docs/` используйте GitHub URLs, иначе опубликованный сайт может вести за пределы Pages artifact.
- Не публикуйте secrets, локальные `.env`, credentials, keys или raw traffic payloads.
- При изменении deployment behavior обновляйте одновременно `docs/deployment.md`, `deploy/README.md` и relevant compose manifests.
- При изменении compatibility behavior обновляйте `docs/api-compatibility.md` и `docs/client-parameter-compatibility.md`.
