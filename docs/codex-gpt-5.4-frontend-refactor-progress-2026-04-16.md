# Frontend Refactor Progress

Дата старта: 2026-04-16
Основной план: [codex-gpt-5.4-frontend-refactor-2026-04-16.md](/Users/riyakupov/code_projects/gpt2giga/docs/codex-gpt-5.4-frontend-refactor-2026-04-16.md)

## Правила ведения

- Этот файл обновляется после каждого законченного slice.
- Каждый законченный slice после релевантных проверок фиксируется отдельным commit.
- В журнале остаются только фактические изменения, проверки и следующий шаг.

## Slice Log

### Slice 1

Статус: `done`

Цель:

- подготовить инфраструктуру child pages и secondary nav;
- начать split `Setup` и `Settings` без смены frontend stack;
- обновить server-side console routes и route tests.

Планируемый объём:

- расширить `PageId` и route map;
- добавить shared helper для subpage navigation;
- перевести `Setup` в hub + step pages;
- перевести `Settings` в hub + section pages;
- завести совместимость для `settings?section=...`.

Фактически сделано:

- добавлены child pages и route metadata для `Setup`, `Settings`, `Files & Batches`;
- добавлен shared secondary nav helper и подключён в `Setup`, `Settings`, `Files & Batches`;
- `Setup` переведён в hub + отдельные страницы `claim/application/gigachat/security`;
- `Settings` переведён в hub + отдельные страницы `application/observability/gigachat/security/history`;
- добавлена compatibility-логика для `settings?section=...`;
- обновлены server-side console routes и integration test на доступность новых URL;
- runtime admin assets пересобраны через `npm run build:admin`.

Проверки:

- `npm run build:admin`
- `uv run pytest tests/integration/app/test_admin_console_settings.py tests/integration/app/test_system_router_extra.py -q`
- `uv run ruff check .`
- `uv run ruff format --check .`

Результат проверок:

- `npm run build:admin` — green
- `uv run pytest tests/integration/app/test_admin_console_settings.py tests/integration/app/test_system_router_extra.py -q` — 40 passed
- `uv run ruff check .` — green
- `uv run ruff format --check .` — green

Следующий шаг:

- выделить реальный focused split для `Files` / `Batches`, чтобы child pages перестали быть общим workbench с разными URL и получили отдельные surface-level layouts.

### Slice 2

Статус: `done`

Цель:

- довести `Files & Batches` от route-level split до реального UX split;
- развести `files` и `batches` по отдельным рабочим поверхностям;
- закрепить page-specific URL/state contract для новых страниц.

Планируемый объём:

- превратить `/admin/files-batches` в summary-first hub;
- сделать `/admin/files` file-first страницей;
- сделать `/admin/batches` batch-first страницей;
- убрать общую перегруженную поверхность с новых child pages;
- обновить asset/tests под новый copy и split.

Фактически сделано:

- `/admin/files-batches` переведён в hub с кратким summary, recent activity и handoff links;
- `/admin/files` переведён в file-first surface с upload, file inventory, preview и переходом в batch composer;
- `/admin/batches` переведён в batch-first surface с batch create, lifecycle review и output handoff;
- `files-batches` view/bindings/serializers/state разрезаны под page-specific behavior;
- закреплён page-aware query/state contract:
  `files` хранит file-centric filters/selection, `batches` хранит batch-centric filters и `compose_input`;
- обновлены runtime admin assets через `npm run build:admin`;
- обновлён integration asset-test под новый split и новый copy.

Проверки:

- `npm run build:admin`
- `uv run pytest tests/integration/app/test_admin_console_settings.py tests/integration/app/test_system_router_extra.py -q`
- `uv run ruff check gpt2giga tests`
- `uv run ruff format --check gpt2giga tests`

Результат проверок:

- `npm run build:admin` — green
- `uv run pytest tests/integration/app/test_admin_console_settings.py tests/integration/app/test_system_router_extra.py -q` — 40 passed
- `uv run ruff check gpt2giga tests` — green
- `uv run ruff format --check gpt2giga tests` — green

Commit:

- `b489f12` — `refactor: split admin files and batches surfaces`

Следующий шаг:

- сделать visual density / responsive pass для form-centric child pages, прежде всего `Setup`, `Settings`, `/admin/files` и `/admin/batches`.

### Slice 3

Статус: `done`

Цель:

- снизить визуальную плотность на form-centric child pages;
- сузить и структурировать `Setup` / `Settings` focused forms;
- улучшить responsive collapse для `/admin/files` и `/admin/batches`.

Планируемый объём:

- добавить shared form/layout primitives для спокойных form surfaces;
- перегруппировать control-plane формы в более явные секции;
- сузить main form panels и облегчить side posture panels;
- обновить form surfaces в `files` / `batches`;
- пересобрать runtime assets и проверить shell/integration smoke.

Фактически сделано:

- добавлен shared helper `renderFormSection(...)` для повторяющихся form sections;
- `Setup` и `Settings` focused pages переведены на более узкий main-column pattern через `panel--measure`, а side posture cards сделаны легче и предсказуемее через `panel--aside`;
- control-plane формы `application`, `gigachat`, `security`, `observability` перегруппированы в явные секции с intro/surface hierarchy вместо длинного плоского stack layout;
- `files` и `batches` получили calmer form shells для filters/upload/queue workflows;
- в `console.css` добавлены shared form-shell styles и более ранний responsive collapse для form grids;
- runtime admin assets пересобраны через `npm run build:admin`.

Проверки:

- `npm run build:admin`
- `uv run pytest tests/integration/app/test_admin_console_settings.py tests/integration/app/test_system_router_extra.py -q`
- `uv run ruff check gpt2giga tests`
- `uv run ruff format --check gpt2giga tests`

Результат проверок:

- `npm run build:admin` — green
- `uv run pytest tests/integration/app/test_admin_console_settings.py tests/integration/app/test_system_router_extra.py -q` — 40 passed
- `uv run ruff check gpt2giga tests` — green
- `uv run ruff format --check gpt2giga tests` — green

Commit:

- `377ff16` — `refactor: polish admin form surfaces`

Следующий шаг:

- при необходимости сделать отдельный stretch-slice для `Traffic`: либо ещё сильнее уменьшить плотность summary page, либо разрезать её на `requests/errors/usage` child pages без перегрузки rail.

### Slice 4

Статус: `done`

Цель:

- закрыть optional `Traffic` split отдельным чистым slice;
- превратить `/admin/traffic` в summary-first hub;
- вынести request/error/usage drill-down на отдельные страницы без удлинения left rail.

Планируемый объём:

- добавить child pages `traffic-requests`, `traffic-errors`, `traffic-usage`;
- подключить reusable secondary nav для `Traffic`;
- разрезать `Traffic` на hub + focused request/error/usage surfaces;
- обновить server-side console routes и asset tests под новый split;
- пересобрать runtime admin assets.

Фактически сделано:

- добавлены page ids, route metadata и secondary nav для `traffic`, `traffic-requests`, `traffic-errors`, `traffic-usage`;
- `/admin/traffic` переведён в summary-first hub с lane cards для requests/errors/usage и отдельным scope/handoff surface вместо одной перегруженной страницы;
- `/admin/traffic-requests` вынесен в request-first surface с собственными filters, request table, inspector/handoff и error-lane handoff;
- `/admin/traffic-errors` вынесен в error-first surface с собственными filters, error table, inspector/handoff и request-lane handoff;
- `/admin/traffic-usage` вынесен в usage-first surface с provider/key rollups, отдельным inspector/handoff и возвратом в request evidence только по необходимости;
- navigation между traffic child pages сохраняет текущие filters/query scope;
- обновлены server-side console route inventory и integration tests;
- runtime admin assets пересобраны через `npm run build:admin`.

Проверки:

- `npm run build:admin`
- `uv run pytest tests/integration/app/test_admin_console_settings.py tests/integration/app/test_system_router_extra.py -q`
- `uv run ruff check gpt2giga tests`
- `uv run ruff format --check gpt2giga tests`

Результат проверок:

- `npm run build:admin` — green
- `uv run pytest tests/integration/app/test_admin_console_settings.py tests/integration/app/test_system_router_extra.py -q` — 40 passed
- `uv run ruff check gpt2giga tests` — green
- `uv run ruff format --check gpt2giga tests` — green

Commit:

- `pending (record actual hash from git history after commit; no amend)` — `refactor: split admin traffic surfaces`

Следующий шаг:

- при необходимости сделать короткий follow-up только на copy/spacing polish внутри новых traffic child pages; базовый refactor по плану уже закрыт без дальнейшего route split.
