# Документация

Сайт собирается из Markdown-файлов в `docs/` через Docusaurus wrapper в
`docs-site/` и публикуется на GitHub Pages.

## Локальная сборка

Установите Node.js `20+`, затем зависимости Docusaurus:

```sh
make docs-install
```

Соберите все локали:

```sh
make docs-build
```

Для локального preview готового артефакта:

```sh
make docs
```

По умолчанию сайт доступен на `http://127.0.0.1:3000/`. Команда собирает и
обслуживает все настроенные локали, поэтому language switcher работает локально.

Для быстрой разработки одной локали с hot reload:

```sh
make docs-dev
```

Docusaurus dev server обслуживает одну локаль за запуск. Для русской локали:

```sh
make docs-dev-ru
```

Переключение между English и Russian проверяйте через `make docs` или
`make docs-preview`.

## Что публикуется

Публичный сайт включает:

- пользовательские руководства из `docs/*.md`;
- architecture notes из `docs/architecture/`;
- русские переводы из
  `docs-site/i18n/ru/docusaurus-plugin-content-docs/current/`;
- ссылки на runnable examples и integration guides в репозитории;
- GitHub-ссылки на deployment manifests и другие файлы вне `docs/`.

Игнорируемые `docs/internal/**` и `docs/codex/**` — локальное coordination state,
а не источник публичного сайта.

## Правила обновления

- Держите README, `docs/index.md`, русскую главную страницу и
  `docs-site/sidebars.ts` согласованными по основным документам.
- Для файлов вне `docs/` используйте GitHub URL: относительная ссылка на
  опубликованном Pages-сайте может уйти за границы артефакта.
- Обновляйте English source и соответствующую русскую страницу в одном change
  set; сохраняйте code blocks, warnings и ограничения поведения.
- Не публикуйте секреты, локальные `.env`, credentials, keys, private code или
  raw traffic payloads.
- При изменении deployment одновременно обновляйте `docs/deployment.md`,
  русскую локаль, `deploy/README.md` и соответствующие Compose manifests.
- При изменении compatibility обновляйте `docs/api-compatibility.md`,
  `docs/client-parameter-compatibility.md`, русские локали и runnable examples.
## Проверка перед PR

```sh
python3 scripts/check_docs.py
make docs-build
git diff --check
```

После сборки просмотрите изменённые страницы в браузере на desktop и узкой
ширине, проверьте navigation, search, language switcher, code copy и отсутствие
ошибок console.
