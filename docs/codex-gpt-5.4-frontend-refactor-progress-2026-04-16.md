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

- `c930ea4` — `refactor: split admin traffic surfaces`

Следующий шаг:

- при необходимости сделать короткий follow-up только на copy/spacing polish внутри новых traffic child pages; базовый refactor по плану уже закрыт без дальнейшего route split.

### Slice 5

Статус: `done`

Цель:

- сделать короткий follow-up на новые `Traffic` child pages;
- уменьшить ощущение длинного support-tail на focused traffic surfaces;
- ещё сильнее увести raw diagnostics на вторичный план без потери handoff UX.

Планируемый объём:

- облегчить нижний support-row на `traffic-requests`, `traffic-errors`, `traffic-usage`;
- перегруппировать inspector в более явные posture/handoff blocks;
- переименовать raw payload disclosure в менее агрессивный snapshot copy;
- пересобрать runtime assets и проверить asset-level integration smoke.

Фактически сделано:

- на focused `Traffic` pages support content разложен в более спокойный `8/4` row вместо full-width tail: companion workflow остаётся главным, а guide card уходит в `aside`;
- `Request/Error/Usage inspector` перегруппированы в `Current posture` и `Selection and handoff`, чтобы selection summary и next-step actions читались раньше raw JSON;
- raw diagnostics disclosure переименован в `Current scope snapshot`, а selection-driven snapshots получили более мягкий copy (`Selected request snapshot`, `Selected error snapshot`, `Selected usage-* snapshot`);
- runtime admin assets пересобраны через `npm run build:admin`;
- progress-log дополнен фактическим hash предыдущего traffic-slice.

Проверки:

- `npm run build:admin`
- `uv run pytest tests/integration/app/test_system_router_extra.py -q`
- `uv run ruff check gpt2giga tests`
- `uv run ruff format --check gpt2giga tests`

Результат проверок:

- `npm run build:admin` — green
- `uv run pytest tests/integration/app/test_system_router_extra.py -q` — 25 passed
- `uv run ruff check gpt2giga tests` — green
- `uv run ruff format --check gpt2giga tests` — green

Commit:

- `e04c35f` — `refactor: polish admin traffic follow-up`

Следующий шаг:

- при необходимости делать только общий cleanup pass по copy/consistency между `Traffic`, `Logs`, `Providers`, `System`; route-level refactor для admin console закрыт.

### Slice 6

Статус: `done`

Цель:

- сделать follow-up cleanup для `Logs` после split `Traffic`;
- снизить плотность deep-dive surface и выровнять handoff copy с `Traffic`;
- увести raw snapshots и stream internals на вторичный план без изменения admin API.

Планируемый объём:

- перестроить `/admin/logs` в более спокойный `8/4` layout;
- перевести filters в более узкий form-shell вместо full-width stack;
- собрать selection/handoff summary в отдельный aside inspector;
- смягчить copy для raw context и SSE diagnostics;
- пересобрать runtime assets и обновить integration asset assertions.

Фактически сделано:

- `Logs` переведён на более спокойный layout: workflow guide остаётся summary-first, filters живут в `panel--measure`, а posture/handoff и live-tail controls вынесены в отдельные `aside` surfaces;
- filters собраны в `form-shell` с секциями `Tail window`, `Request pinning`, `Event scope`, чтобы deep-dive page перестала выглядеть как одна длинная техническая форма;
- selection inspector перестроен в `Current posture` и `Selection and handoff`, а raw disclosure переименован в `Current scope snapshot`;
- stream panel смягчён: diagnostics теперь явно secondary (`Live stream diagnostics`), а основной акцент остаётся на rendered tail и predictable handoff обратно в `Traffic`;
- binding copy обновлён под новые snapshot labels: `Selected request snapshot`, `Selected error snapshot`, `Selected tail context snapshot`;
- runtime admin assets пересобраны через `npm run build:admin`;
- integration asset-test обновлён под новый `Logs` copy и layout affordances.

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

- `4d49a46` — `refactor: polish admin logs surface`

Следующий шаг:

- если продолжать дальше, делать уже только небольшой consistency pass по `Providers` / `System` / `Overview`; основные route-level и workflow-level цели плана закрыты.

### Slice 7

Статус: `done`

Цель:

- сделать завершающий consistency pass по summary-first surfaces;
- выровнять `Overview`, `Providers` и `System` под уже введённый handoff/guide pattern;
- ещё сильнее увести staged diagnostics на вторичный план без нового route split.

Планируемый объём:

- сделать `Overview` более summary-first и добавить явный guide/handoff surface;
- перестроить `Providers` в более спокойный `measure/aside` layout без потери capability coverage;
- сделать `System` более staged: summary/readiness раньше, guides и export отдельно;
- пересобрать runtime admin assets и обновить targeted asset assertions.

Фактически сделано:

- `Overview` переведён на более явный handoff pattern: основная posture-панель и workflow aside получили `measure/aside` layout, а recent errors вынесены в отдельный summary-first handoff surface вместо условного full-width tail;
- в `Overview` добавлен отдельный `Guide and troubleshooting` surface с handoff в operator guide, traffic workflow и troubleshooting map;
- `Providers` перегруппирован в более спокойный summary-first flow: `Executive summary`, `Capability coverage` и `Provider briefs` стали primary `measure` surfaces, а `Provider workflow handoff`, `Guide and troubleshooting` и `Backend posture` ушли в `aside`;
- staged route diagnostics в `Providers` смягчены через copy `Current route-family snapshot` и `Full provider surface matrix`, чтобы raw route detail читался как вторичный слой;
- `System` переведён на более staged layout: `Executive summary` и `Readiness` стали primary surfaces, добавлен отдельный `Guide and troubleshooting`, copy/export смягчены до `Copy system snapshot` и `Current system snapshot`;
- runtime admin assets пересобраны через `npm run build:admin`;
- integration asset-test обновлён под новый summary-surface copy для `Overview`, `Providers` и `System`.

Проверки:

- `npm run build:admin`
- `uv run pytest tests/integration/app/test_system_router_extra.py -q`
- `uv run ruff check gpt2giga tests`
- `uv run ruff format --check gpt2giga tests`

Результат проверок:

- `npm run build:admin` — green
- `uv run pytest tests/integration/app/test_system_router_extra.py -q` — 25 passed
- `uv run ruff check gpt2giga tests` — green
- `uv run ruff format --check gpt2giga tests` — green

Commit:

- `110844c` — `refactor: align admin summary surfaces`

Следующий шаг:

- базовый frontend-refactor по этому плану закрыт; если продолжать дальше, то только мелкий shell/copy cleanup без новых workflow slices.

### Slice 8

Статус: `done`

Цель:

- сделать завершающий shell-level consistency pass без нового route split;
- уменьшить постоянную многословность left rail;
- вынести текущий workflow/surface context в hero, чтобы summary-first pages ощущались единым console shell.

Планируемый объём:

- сделать rail компактнее и оставить expanded copy только вокруг активного workflow;
- добавить hero-level workflow/surface context поверх page-specific actions;
- закрепить новый shell contract integration assertions без изменения admin API.

Фактически сделано:

- left rail сделан спокойнее: workflow group copy и nav meta больше не доминируют постоянно, а раскрываются вокруг активной или наведённой группы/ссылки;
- активный workflow в rail теперь явно подсвечивается через `nav-group--active`, а активный entry получает `aria-current="page"`;
- в shell hero добавлен отдельный `hero-context` слой с `workflow-chip`, `surface-chip` и page-specific context copy, который наполняется из `PAGE_META`/`WORKFLOW_META`;
- обновлён shell HTML (`data-workflow` на nav groups) и runtime app logic, чтобы rail и hero читались как одна система;
- runtime admin assets пересобраны через `npm run build:admin`;
- integration assertions расширены под новый shell contract и stylesheet hooks.

Проверки:

- `npm run build:admin`
- `uv run pytest tests/integration/app/test_system_router_extra.py -q`
- `uv run ruff check gpt2giga tests`
- `uv run ruff format --check gpt2giga tests`

Результат проверок:

- `npm run build:admin` — green
- `uv run pytest tests/integration/app/test_system_router_extra.py -q` — 25 passed
- `uv run ruff check gpt2giga tests` — green
- `uv run ruff format --check gpt2giga tests` — green

Commit:

- `8266954` — `refactor: compact admin shell navigation`

Следующий шаг:

- если продолжать дальше, то только очень мелкий accessibility/copy pass по shell и page-level CTA; route/layout refactor по этому плану закрыт.

### Slice 9

Статус: `done`

Цель:

- сделать завершающий shell-level accessibility/navigation follow-up без нового route split;
- сохранить deep-link/handoff query contract при SPA-переходах внутри `/admin`;
- выровнять shell semantics для left rail и secondary nav.

Планируемый объём:

- исправить internal navigation так, чтобы `/admin/...?...` не терял `search/hash`;
- добавить shell landmarks и skip-link для keyboard/screen-reader navigation;
- закрепить focus-management на page heading после route change;
- обновить integration assertions под новый shell/accessibility contract.

Фактически сделано:

- в `AdminApp` добавлен `navigateToLocation(...)`: internal `/admin` links теперь сохраняют `pathname + search + hash`, поэтому handoff из `Traffic`/`Logs`/`Providers` больше не теряет deep-link scope при SPA-navigation;
- после route change и browser `popstate` shell теперь переводит focus на `page-title`, чтобы child pages и direct handoff читались предсказуемо для keyboard/screen-reader flows, но обычные same-page rerender-ы не перехватывают focus;
- HTML shell получил `skip-link`, `aria-label` для primary console nav и фокусируемый `page-title`;
- shared `renderSubpageNav(...)` переведён на семантический `nav` с явным `aria-label`;
- в `console.css` добавлены skip-link/focus-visible affordances и лёгкий hook для `subpage-nav`;
- runtime admin assets пересобраны через `npm run build:admin`;
- integration asset tests расширены под новый shell contract и проверяют как shell HTML, так и собранный `app.js`.

Проверки:

- `npm run build:admin`
- `uv run pytest tests/integration/app/test_system_router_extra.py -q`
- `uv run pytest tests/integration/app/test_admin_console_settings.py -q`
- `uv run ruff check .`
- `uv run ruff format --check .`

Результат проверок:

- `npm run build:admin` — green
- `uv run pytest tests/integration/app/test_system_router_extra.py -q` — 25 passed
- `uv run pytest tests/integration/app/test_admin_console_settings.py -q` — 15 passed
- `uv run ruff check .` — green
- `uv run ruff format --check .` — green

Commit:

- `b92feb3` — `fix: preserve admin handoff urls and shell focus`

Следующий шаг:

- если продолжать дальше, то уже только точечный CTA/copy polish на отдельных страницах; shell routing, accessibility-basics и handoff URL contract для этого refactor уже закрыты.
