# Frontend Copy Refactor Progress

Дата старта: 2026-04-17
Основной план: [admin-frontend-copy-refactor-2026-04-17.md](/Users/riyakupov/code_projects/gpt2giga/docs/admin-frontend-copy-refactor-2026-04-17.md)

## Правила ведения

- Этот файл обновляется после каждого завершённого slice.
- После каждой выполненной задачи и каждого завершённого slice нужен отдельный commit.
- Завершённый slice не должен оставаться только в working tree.
- В журнале остаются только фактические изменения, проверки и следующий шаг.
- Для каждого slice нужно отдельно фиксировать:
  - статус;
  - цель;
  - планируемый объём;
  - что фактически сделано;
  - какие проверки запускались;
  - результат проверок;
  - commit hash и commit message;
  - следующий шаг.

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

### Slice 2

Статус: `done`

Цель:

- уменьшить copy-density на hub pages второго приоритета и на связанных focused surfaces;
- сделать workflow / guide blocks компактнее без нового structural split;
- сократить helper-text в `Setup`, `Settings`, `Keys`, `System`, `Providers`, `Files`, `Batches`.

Планируемый объём:

- укоротить hub copy в `Setup` и `Settings`;
- убрать лишний explanatory prose в `Keys`, `Providers`, `System`;
- сделать guide blocks компактными/disclosure-first;
- сократить навигационный и inspector copy в `Files & Batches`;
- пересобрать runtime admin assets и обновить integration asserts.

Фактически сделано:

- `Setup` упрощён: короче setup-map и focused nav intros, компактнее bootstrap/status copy, укорочены step card descriptions и security handoff copy;
- `Settings` упрощён: короче map/history/persistence copy, entry cards получили более короткие descriptions, sidebar лишился отдельного intro-параграфа;
- `Keys` упрощён: workflow cards переведены в compact mode, form intro и section intros сокращены, guide block свернут;
- `Providers` упрощён: workflow column стала compact, capability section лишился лишнего intro, route diagnostics и guide block сокращены;
- `System` упрощён: workflow cards стали compact, staged diagnostics/export copy сокращён, guide block свернут;
- `Files & Batches` упрощены: короче workbench navigation, hub/file/batch workflow copy, filter/inspector/helper text и guide blocks;
- runtime admin assets пересобраны через `npm run build:admin`;
- integration tests обновлены под новый copy на system/providers/files-batches surfaces.

Проверки:

- `npm run build:admin`
- `uv run pytest tests/integration/app/test_system_router_extra.py tests/integration/app/test_admin_console_settings.py -q`
- `uv run ruff check tests/integration/app/test_system_router_extra.py`

Результат проверок:

- `npm run build:admin` — green
- `uv run pytest tests/integration/app/test_system_router_extra.py tests/integration/app/test_admin_console_settings.py -q` — 41 passed
- `uv run ruff check tests/integration/app/test_system_router_extra.py` — green

Commit hash и commit message:

- `e0ccc33` — `refactor: trim admin operator copy`

Следующий шаг:

- пройтись по remaining copy-density в shared control-plane form sections и при необходимости дочистить остаточные verbose banners на focused admin pages без нового layout refactor.

### Slice 3

Статус: `done`

Цель:

- уменьшить copy-density в shared control-plane form sections;
- сократить статусный/helper copy вокруг secret fields, pending summaries и observability presets;
- дочистить самый шумный focused surface (`Logs`) без нового layout refactor.

Планируемый объём:

- укоротить shared helper copy в `templates.ts` и `forms.ts`;
- сократить intros/banner copy в `control-plane-sections.ts`;
- укоротить focused setup/settings banner/status copy;
- сделать `Logs` суше: компактнее workflow/scope/inspector/guide text;
- пересобрать runtime admin assets и обновить integration asserts под новый copy.

Фактически сделано:

- `renderSecretField(...)`, pending status copy и live/restart summaries укорочены; dynamic secret helper text в `forms.ts` стал короче;
- shared control-plane sections упрощены: короче section intros, observability preset copy, sink descriptions, OTLP header helper text и setup observability handoff;
- focused `Setup` и `Settings` pages получили более короткие banner messages, status notes и pending messages без смены структуры;
- `Logs` упрощён: короче titles, workflow copy, filter/inspector/helper text, tail context copy и live-stream diagnostics copy; guide block переведён в compact disclosure;
- runtime admin assets пересобраны через `npm run build:admin`;
- integration asserts обновлены под новый `Logs` copy.

Проверки:

- `npm run build:admin`
- `uv run pytest tests/integration/app/test_system_router_extra.py tests/integration/app/test_admin_console_settings.py -q`
- `uv run ruff check tests/integration/app/test_system_router_extra.py`

Результат проверок:

- `npm run build:admin` — green
- `uv run pytest tests/integration/app/test_system_router_extra.py tests/integration/app/test_admin_console_settings.py -q` — 41 passed
- `uv run ruff check tests/integration/app/test_system_router_extra.py` — green

Commit hash и commit message:

- `a938554` — `refactor: trim admin control plane copy`

Следующий шаг:

- пройтись по remaining focused observe/diagnose surfaces (`Traffic`, `Playground`, `Keys`) и добить остаточный explanatory prose в inspector/guide blocks без новой layout wave.
