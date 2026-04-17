# Frontend Copy Refactor Progress

Дата старта: 2026-04-17
Основной план: [admin-frontend-copy-refactor-2026-04-17.md](/Users/riyakupov/code_projects/gpt2giga/docs/admin-frontend-copy-refactor-2026-04-17.md)

## Правила ведения

- Этот файл обновляется после каждого завершённого slice.
- После каждой выполненной задачи и каждого завершённого slice нужен отдельный commit.
- Завершённый slice не должен оставаться только в working tree.
- В журнале остаются только фактические изменения, проверки и следующий шаг.

## Slice Log

### Slice 1

Статус: `done`

Цель:

- уменьшить общую copy-density в shell и shared frontend templates;
- сократить лишний hero и rail context;
- применить более компактные паттерны к самым шумным страницам первого экрана.

Планируемый объём:

- укоротить shell copy в `console.html`;
- убрать лишний hero-context из app shell;
- добавить compact-вариант для `renderWorkflowCard(...)`;
- сделать `renderGuideLinks(...)` пригодным для disclosure / compact use;
- сократить copy на `Overview`, `Playground`, `Traffic`.

Фактически сделано:

- сокращён copy в shell: brand text, workflow-group copy, nav meta, browser-key note;
- убран отдельный `page-context` слой из hero, оставлены title, subtitle и chips;
- сокращены верхнеуровневые subtitles в route metadata для ключевых hub pages;
- `renderWorkflowCard(...)` получил compact mode с optional note;
- `renderGuideLinks(...)` получил compact/disclosure режимы;
- `Overview` переведён на более короткий callout, compact workflow cards и свернутый guide block;
- `Playground` упрощён: убраны лишние section intros, укорочен right rail copy, guide block свернут;
- `Traffic` упрощён: сокращены nav/filter/inspector intros, usage handoff cards сделаны compact, guide blocks свернуты;
- runtime admin assets пересобраны через `npm run build:admin`;
- integration tests обновлены под новый shell и новый copy.

Проверки:

- `npm run build:admin`
- `uv run pytest tests/integration/app/test_admin_console_settings.py tests/integration/app/test_system_router_extra.py -q`

Результат проверок:

- `npm run build:admin` — green
- `uv run pytest tests/integration/app/test_admin_console_settings.py tests/integration/app/test_system_router_extra.py -q` — 41 passed

Следующий шаг:

- пройтись по hub pages второго приоритета (`Setup`, `Settings`, `Keys`, `System`, `Providers`, `Files`, `Batches`) и убрать оставшийся explanatory prose без новой structural split-волны.
