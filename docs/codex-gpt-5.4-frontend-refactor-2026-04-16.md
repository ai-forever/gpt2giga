# Задание для Codex / GPT-5.4: refactor admin frontend gpt2giga

Дата: 2026-04-16
База: локальный архив репозитория + ветка `feature/extend_capabilities`

## Что нужно сделать

Нужно провести **прикладной рефакторинг operator UI** в `gpt2giga`, не переписывая проект на новый frontend stack.

Главная цель:

- сделать `/admin` заметно **проще и чище визуально**;
- убрать ощущение перегруженности;
- исправить места, где контент выглядит тесным, плохо помещается или теряет иерархию;
- разнести тяжёлые workflow на **большее количество отдельных страниц**, которые открываются по своим URL;
- сохранить существующую архитектурную идею: **тонкий HTML shell + TypeScript-модули + runtime assets в optional UI package**.

Это **не redesign ради redesign**. Нужен именно рефакторинг текущего встроенного admin frontend с минимальным риском для runtime.

---

## Обязательный контекст по репозиторию

Перед началом работы опирайся на фактическую структуру репо:

- `gpt2giga/frontend/admin/` — исходники admin UI на TypeScript;
- `packages/gpt2giga-ui/src/gpt2giga_ui/static/admin/` — runtime-ассеты, которые реально раздаёт приложение;
- `packages/gpt2giga-ui/src/gpt2giga_ui/templates/console.html` — shell;
- `gpt2giga/app/admin_ui.py` — загрузка UI-ресурсов;
- `gpt2giga/api/admin/ui.py` — HTML routes для console;
- `gpt2giga/frontend/admin/routes.ts` — список страниц и page metadata;
- `gpt2giga/frontend/admin/pages/index.ts` — registry page renderers;
- `gpt2giga/frontend/admin/types.ts` — `PageId` и общие типы.

Существующий build flow сохраняем:

```bash
npm run build:admin
```

Скомпилированные файлы должны попадать в:

```bash
packages/gpt2giga-ui/src/gpt2giga_ui/static/admin/
```

### Важные ограничения

- Не вводить React/Vue/Svelte/Vite и не тащить тяжёлый frontend framework.
- Не редактировать руками compiled JS в `packages/gpt2giga-ui/src/gpt2giga_ui/static/admin/`.
- Редактировать исходники только в `gpt2giga/frontend/admin/` и потом пересобирать ассеты.
- Не ломать текущие admin API endpoints без необходимости.
- Если нужен новый backend код для UI-роутинга, он должен быть минимальным и совместимым.
- Сохранять разделение:
  - admin/control-plane surface;
  - gateway/data-plane surface.
- Сохранять текущую механику ключей в rail:
  - admin key / bootstrap token;
  - gateway API key.
- Не оставлять законченные изменения только в working tree: каждый завершённый slice после релевантных проверок нужно фиксировать отдельным commit.
- После каждого законченного slice делать отдельный commit.
- Обязательно вести прогресс в `docs/codex-gpt-5.4-frontend-refactor-progress-2026-04-16.md`.
- После каждого законченного slice обязательно обновлять `docs/codex-gpt-5.4-frontend-refactor-progress-2026-04-16.md` и записывать туда:
  - статус slice;
  - цель;
  - планируемый объём;
  - что фактически сделано;
  - какие проверки запускались;
  - результат проверок;
  - commit hash и commit message;
  - следующий запланированный шаг.

---

## Что сейчас не нравится и что именно надо исправить

Ниже не абстрактные пожелания, а конкретная проблема UX.

### 1. Слишком много смыслов на одной странице

Сейчас особенно перегружены:

- `Setup`
- `Settings`
- `Files & Batches`

Там слишком много разных действий, статусов, пояснений и форм в одном экране.

### 2. Важные секции спрятаны как будто внутри одной страницы, хотя по смыслу это отдельные экраны

Особенно это касается:

- шагов bootstrap/setup;
- секций settings;
- file/batch lifecycle;
- части traffic/usage drill-down.

### 3. Визуальная плотность местами слишком высокая

Проблемы, которые нужно снять:

- слишком длинные блоки с описаниями;
- слишком много карточек подряд;
- формы растягиваются слишком широко;
- рядом оказываются блоки разной важности без явного приоритета;
- raw JSON / diagnostic payload слишком легко оказывается в центре внимания.

### 4. Нужны отдельные URL для более мелких workflow

Большие workflow нужно дробить на страницы, а не только на скрываемые секции в пределах одного renderer-а.

Требование пользователя: **если можно, сделать больше отдельных страниц**.

---

## Текущее состояние, от которого нужно оттолкнуться

Сейчас top-level page map в console фактически такой:

- `overview`
- `setup`
- `settings`
- `keys`
- `logs`
- `playground`
- `traffic`
- `providers`
- `files-batches`
- `system`

Также важно учитывать текущее устройство UI:

- shell построен вокруг `console-rail` + `console-hero` + `page-content`;
- основной layout — 12-колоночная grid-сетка;
- left rail сейчас очень информативный, но местами слишком многословный;
- `Settings` уже делится на секции, но пока это в основном **одна страница с внутренним переключателем**;
- `Setup` содержит сразу все bootstrap-шаги на одном экране;
- `Files & Batches` объединяет слишком много разных режимов работы в одном месте.

---

## Целевой результат

Нужен **более чистый, более модульный, более page-driven UI**.

### Что должно получиться по ощущениям

- меньше визуального шума;
- одна страница = одна понятная задача;
- меньше “control room overload”;
- легче открыть нужный URL и сразу понять, где находишься;
- лучше читается на средних экранах и ноутбуках;
- тяжёлые workflows разбиты на smaller surfaces;
- raw diagnostics остаётся доступной, но не давит на основной UX.

---

## Целевая информационная архитектура

### Сохраняем основные workflow-группы

Левая навигация должна остаться сравнительно компактной. Не нужно превращать left rail в бесконечный список всех подстраниц.

Оставь в rail в первую очередь **основные workflow entrypoints**, а детальную навигацию перенеси в **secondary page nav** внутри соответствующих разделов.

### Обязательная новая структура

#### Start

- `/admin` — `overview`
- `/admin/setup` — setup hub / progress page
- `/admin/setup-claim`
- `/admin/setup-application`
- `/admin/setup-gigachat`
- `/admin/setup-security`
- `/admin/playground`

#### Configure

- `/admin/settings` — settings hub / summary page
- `/admin/settings-application`
- `/admin/settings-observability`
- `/admin/settings-gigachat`
- `/admin/settings-security`
- `/admin/settings-history`
- `/admin/keys`

#### Observe

- `/admin/traffic` — observe hub / summary page
- `/admin/logs`

#### Diagnose

- `/admin/providers`
- `/admin/files-batches` — overview / workbench hub
- `/admin/files`
- `/admin/batches`
- `/admin/system`

### Optional stretch goal

Если останется время и изменения будут чистыми, можно дополнительно разрезать `Traffic`:

- `/admin/traffic-requests`
- `/admin/traffic-errors`
- `/admin/traffic-usage`

Но это уже **не первый приоритет**. Первый приоритет — `Setup`, `Settings`, `Files/Batches`.

---

## Навигационный принцип

### 1. Rail остаётся коротким

В left rail оставь примерно те же основные entrypoints, что и сейчас:

- Overview
- Setup
- Playground
- Settings
- API Keys
- Traffic
- Logs
- Providers
- Files & Batches
- System

### 2. Для новых child pages сделать local secondary nav

Добавь общий reusable паттерн локальной навигации внутри страницы:

- для `Setup`: `Overview`, `Claim`, `Application`, `GigaChat`, `Security`
- для `Settings`: `Overview`, `Application`, `Observability`, `GigaChat`, `Security`, `History`
- для `Files & Batches`: `Overview`, `Files`, `Batches`
- для `Traffic` stretch phase: `Overview`, `Requests`, `Errors`, `Usage`

Это должна быть не новая SPA-магия, а простой и понятный UI primitive:

- чипы / pills / compact tabs;
- ссылки на реальные отдельные URL;
- явное выделение текущей child page.

### 3. Хабы должны остаться

`/admin/setup`, `/admin/settings`, `/admin/files-batches`, `/admin/traffic` не удалять.

Они должны стать **summary-first hub pages**, а не ещё одной перегруженной mega-page.

---

## Что именно нужно поменять по страницам

## A. Setup

### Сейчас

`Setup` перегружен: progress, claim, application posture, GigaChat auth, security bootstrap, observability handoff, finish state — всё в одном экране.

### Нужно

Сделать:

- `setup` как hub page со статусом прогресса, warnings и ссылками на шаги;
- `setup-claim` как отдельную страницу только для claim workflow;
- `setup-application` как отдельную страницу для application posture;
- `setup-gigachat` как отдельную страницу для GigaChat credentials + connection test;
- `setup-security` как отдельную страницу для security bootstrap + global key action.

### Важно

- observability не нужно делать частью bootstrap-critical path;
- link/handoff из setup в observability settings должен остаться;
- кнопки next/back между шагами должны быть простыми и очевидными;
- на hub page показывать только прогресс, readiness, warnings и next recommended step.

---

## B. Settings

### Сейчас

`Settings` уже разбит по смыслу, но по UX это всё ещё одна страница с `?section=` переключателем.

### Нужно

Преобразовать это в отдельные страницы:

- `settings` — hub / summary / entrypoint;
- `settings-application`;
- `settings-observability`;
- `settings-gigachat`;
- `settings-security`;
- `settings-history`.

### Важно

- формы должны остаться переиспользуемыми через текущие shared helpers;
- не терять текущую логику pending diff / save status / rollback / connection test;
- query-параметр `?section=` больше не должен быть основным способом навигации между крупными секциями;
- можно оставить compatibility behavior: если пришли на `/admin/settings?section=observability`, пользователь должен оказаться на правильной child page.

---

## C. Files & Batches

### Сейчас

`Files & Batches` объединяет upload, batch creation, inventory filters, inspector, content preview, batch/output workflow.

### Нужно

Сделать:

- `files-batches` как workbench hub;
- `files` — upload + file inventory + file preview;
- `batches` — batch create + batch inventory + output/result workflow.

### Важно

- inspector/action model можно переиспользовать;
- если удобно, передавай selection через query params или явные input fields;
- не теряй связь с playground, logs и traffic;
- raw metadata/content должны быть раскрываемыми по желанию, а не доминировать по умолчанию.

---

## D. Traffic

### Первый проход

На первом проходе достаточно:

- оставить `traffic` summary-first;
- визуально облегчить страницу;
- убрать лишнюю плотность;
- сделать явный handoff в `Logs` и при необходимости в будущие child pages.

### Stretch

Если после основных задач останется ресурс и код получится чистым, можно вынести:

- requests view;
- errors view;
- usage view.

Но это не должно задерживать основной refactor.

---

## Что нужно сделать по визуальному слою

## 1. Уменьшить информационный шум

Нужно сделать UI визуально спокойнее:

- сократить объём второстепенного текста на экране;
- не держать длинные пояснения всегда открытыми;
- тяжёлые diagnostic/details блоки прятать в `details` или secondary sections;
- уменьшить количество одинаково “важных” карточек на одном экране.

## 2. Исправить ощущение, что что-то не помещается

Требования:

- формы не должны растягиваться слишком широко;
- ключевые form pages должны иметь более узкую readable column;
- таблицы и code blocks могут оставаться full-width, но form-centric страницы должны быть уже и спокойнее;
- не допускать неприятного горизонтального overflow на основных рабочих сценариях.

## 3. Сделать иерархию очевиднее

На каждой странице должен быть понятен ответ на три вопроса:

- где я нахожусь;
- что здесь главное действие;
- куда идти дальше.

Для этого:

- добавь secondary nav / breadcrumb-like cue;
- ограничь количество primary actions;
- сделай clearer distinction между summary, form, diagnostics и raw payload.

## 4. Улучшить адаптивность без тяжёлого rewrite

Нужно улучшить поведение на laptop/tablet-width:

- аккуратнее переломить grid;
- раньше переводить многоколонные формы в 1 колонку;
- сделать более предсказуемым поведение left rail;
- следить, чтобы secondary nav не ломал layout.

---

## Конкретные инженерные требования

### 1. Не устраивать rewrite всего frontend

Нужен refactor по существующей архитектуре:

- thin page entrypoints;
- shared templates/helpers;
- page-local folders там, где это оправдано.

### 2. Желательная структура кода

По мере необходимости добавляй page-local папки по аналогии с уже существующими slice-структурами (`logs`, `playground`, `traffic`, `files-batches`).

Подход правильный такой:

- `render-*.ts` — тонкий entrypoint;
- `view.ts` — layout/render helpers;
- `bindings.ts` — DOM wiring;
- `state.ts` — state/query types;
- `serializers.ts` — URL/query/payload mapping.

### 3. Нужен новый shared primitive для subpage navigation

Добавь переиспользуемый helper, условно уровня:

- `renderSectionNav(...)`
- `renderSubpageNav(...)`
- или аналогичный shared component в `templates.ts`

Он должен уметь:

- показывать child pages внутри workflow;
- подсвечивать активную страницу;
- быть компактным;
- генерировать реальные ссылки.

### 4. Роутинг нужно расширить корректно

Нужно обновить:

- `gpt2giga/frontend/admin/types.ts`
- `gpt2giga/frontend/admin/routes.ts`
- `gpt2giga/frontend/admin/pages/index.ts`
- `gpt2giga/api/admin/ui.py`

Новые child pages должны реально открываться сервером как console shell routes.

### 5. Не сломать старые entrypoints

Старые страницы должны продолжать работать:

- `/admin/setup`
- `/admin/settings`
- `/admin/files-batches`
- `/admin/traffic`

Но их смысл должен стать hub-oriented, а не overloaded mega-page.

### 6. Обновить тесты

Нужно обновить и/или добавить тесты как минимум на:

- доступность новых console routes;
- сохранение старых route entrypoints;
- раздачу новых compiled assets, если добавятся новые page-local JS modules;
- совместимость shell routing;
- при необходимости — capability/admin route inventory, если он отражает список console pages.

---

## Файлы, которые почти наверняка придётся тронуть

### UI shell / routing

- `packages/gpt2giga-ui/src/gpt2giga_ui/templates/console.html`
- `packages/gpt2giga-ui/src/gpt2giga_ui/static/admin/console.css` (через rebuild из source)
- `gpt2giga/frontend/admin/types.ts`
- `gpt2giga/frontend/admin/routes.ts`
- `gpt2giga/frontend/admin/app.ts`
- `gpt2giga/frontend/admin/templates.ts`
- `gpt2giga/frontend/admin/pages/index.ts`

### Setup / Settings

- `gpt2giga/frontend/admin/pages/render-setup.ts`
- `gpt2giga/frontend/admin/pages/render-settings.ts`
- `gpt2giga/frontend/admin/pages/control-plane-sections.ts`
- `gpt2giga/frontend/admin/pages/control-plane-form-bindings.ts`
- новые child page modules для setup/settings

### Files / Batches

- `gpt2giga/frontend/admin/pages/render-files-batches.ts`
- `gpt2giga/frontend/admin/pages/files-batches/*`
- новые страницы `files` / `batches`

### Backend HTML routes

- `gpt2giga/api/admin/ui.py`

### Tests

- `tests/integration/app/test_admin_console_settings.py`
- `tests/integration/app/test_system_router_extra.py`
- при необходимости другие admin UI tests

---

## Предпочтительный план выполнения

## Phase 1 — routing + navigation primitive

Сначала сделай инфраструктуру для child pages:

- расширь `PageId`;
- добавь новые route meta;
- добавь server-side shell routes;
- сделай shared secondary nav helper;
- внедри этот helper хотя бы в `Setup`, `Settings`, `Files & Batches`.

Отдельный commit.

## Phase 2 — split Setup

- преврати `/admin/setup` в hub page;
- вынеси claim/application/gigachat/security в отдельные страницы;
- упрости старую setup-страницу;
- оставь понятные переходы между шагами.

Отдельный commit.

## Phase 3 — split Settings

- преврати `/admin/settings` в hub page;
- вынеси application/observability/gigachat/security/history в child pages;
- убери зависимость UX от `?section=` как основного механизма.

Отдельный commit.

## Phase 4 — split Files & Batches

- преврати `/admin/files-batches` в hub;
- добавь `/admin/files` и `/admin/batches`;
- разнеси формы и inventory по отдельным страницам;
- сделай UX inspector/preview менее тяжёлым.

Отдельный commit.

## Phase 5 — visual polish / responsive pass

- уменьшить визуальную плотность;
- сузить form-centric layouts;
- улучшить spacing и grid behavior;
- убрать места, где UI выглядит тесным или overloaded.

Отдельный commit.

## Phase 6 — optional Traffic split

Только если основной refactor уже чистый и стабильный.

---

## UX-правила, которым нужно следовать

- Одна child page = одна основная задача.
- Не более 1 главной формы на child page, если только это не hub.
- Raw JSON никогда не должен быть главным элементом страницы.
- Основные CTA должны быть короткими и понятными.
- Поясняющий текст — короче; глубинные инструкции — в secondary/help surfaces.
- Новые страницы должны облегчать UX, а не плодить хаос в навигации.
- Left rail не должен становиться длиннее и тяжелее, чем сейчас.

---

## Acceptance criteria

Работа считается успешной, если выполнено следующее.

### Информационная архитектура

- `Setup`, `Settings`, `Files & Batches` больше не являются перегруженными mega-pages.
- Есть больше отдельных открываемых страниц с реальными URL.
- Основные hub pages остались, но стали summary-first.
- Child pages доступны напрямую по URL и нормально работают через browser back/forward.

### UX

- UI визуально спокойнее и легче читается.
- Формы больше не растягиваются неприятно широко.
- На основных form pages нет ощущения, что блоки “не помещаются”.
- Secondary navigation делает структуру разделов очевидной.
- Диагностические данные доступны, но не мешают основному workflow.

### Инженерно

- Нет нового тяжёлого frontend stack.
- Page entrypoints остаются тонкими.
- Shared primitives переиспользуются.
- Ассеты пересобраны через `npm run build:admin`.
- Тесты под новые routes и shell routing обновлены.

---

## Минимальный набор команд проверки

```bash
npm run build:admin
uv run pytest tests/integration/app/test_admin_console_settings.py tests/integration/app/test_system_router_extra.py -q
```

Если тронут backend routing или route inventory, дополнительно прогнать релевантные admin/integration tests.

Перед финализацией также держать зелёными:

```bash
uv run ruff check .
uv run ruff format --check .
```

---

## Что не нужно делать

- Не переносить весь UI на React.
- Не делать декоративный redesign без архитектурного выигрыша.
- Не добавлять новые страницы, которые отличаются только copy и не уменьшают перегрузку.
- Не оставлять старые mega-pages как есть и просто дублировать ссылки.
- Не делать child pages частью query-only navigation, если можно дать им отдельный URL.

---

## Практическое указание для первого прохода

Если нужно выбрать только один главный результат первого цикла, то это такой набор:

1. разрезать `Setup` на hub + step pages;
2. разрезать `Settings` на hub + section pages;
3. разрезать `Files & Batches` на hub + `Files` + `Batches`;
4. добавить shared secondary nav;
5. сделать спокойнее layout form-centric страниц.

Именно это даст наибольший UX-эффект при умеренном риске.

---

## Формат работы Codex

Работай как инженер, а не как “генератор идей”.

Нужно:

- сначала внести реальные изменения в код;
- после каждого законченного slice прогнать релевантные проверки;
- потом делать отдельный commit;
- после этого обязательно обновить `docs/codex-gpt-5.4-frontend-refactor-progress-2026-04-16.md` фактической записью по завершённому slice;
- в конце обновить документы, если page map или UX-подход заметно изменились.

Если по ходу увидишь возможность сделать чище и проще без расширения риска — делай. Но не уходи в бесконечный rewrite.

---

## Короткий prompt для запуска в Codex

Сделай refactor встроенного admin frontend в репозитории `gpt2giga` без смены frontend stack.

Контекст:

- исходники UI: `gpt2giga/frontend/admin/`
- runtime assets: `packages/gpt2giga-ui/src/gpt2giga_ui/static/admin/`
- HTML shell: `packages/gpt2giga-ui/src/gpt2giga_ui/templates/console.html`
- server-side console routes: `gpt2giga/api/admin/ui.py`
- page map: `gpt2giga/frontend/admin/routes.ts`

Цель:

- сделать UI менее перегруженным;
- убрать места, где контент выглядит тесным и плохо читается;
- разрезать большие workflow на большее количество отдельных страниц с реальными URL;
- сохранить thin shell + TypeScript modules + build через `npm run build:admin`.

Первый приоритет:

1. превратить `/admin/setup` в hub и вынести child pages:
   - `/admin/setup-claim`
   - `/admin/setup-application`
   - `/admin/setup-gigachat`
   - `/admin/setup-security`
2. превратить `/admin/settings` в hub и вынести child pages:
   - `/admin/settings-application`
   - `/admin/settings-observability`
   - `/admin/settings-gigachat`
   - `/admin/settings-security`
   - `/admin/settings-history`
3. превратить `/admin/files-batches` в hub и добавить:
   - `/admin/files`
   - `/admin/batches`
4. добавить shared secondary navigation primitive для child pages;
5. визуально облегчить form-centric страницы и улучшить responsive behavior.

Ограничения:

- не добавляй React/Vue/Svelte/Vite;
- не редактируй compiled JS руками;
- редактируй TS source и затем пересобери ассеты;
- сохраняй старые hub routes рабочими;
- не ломай существующие admin API endpoints без необходимости;
- после каждого законченного slice делай отдельный commit.

Что обновить обязательно:

- `gpt2giga/frontend/admin/types.ts`
- `gpt2giga/frontend/admin/routes.ts`
- `gpt2giga/frontend/admin/pages/index.ts`
- `gpt2giga/api/admin/ui.py`
- нужные page modules
- integration tests для новых console routes

Что проверить:

```bash
npm run build:admin
uv run pytest tests/integration/app/test_admin_console_settings.py tests/integration/app/test_system_router_extra.py -q
uv run ruff check .
uv run ruff format --check .
```

Работай по этапам, не делай бесконечный rewrite. Главный результат — меньше перегрузки и больше отдельных понятных страниц.

---

## Продолжение плана от текущего состояния ветки

Ниже продолжение плана не с нуля, а **от уже существующего состояния кода** в текущей ветке.

### Что уже фактически есть в коде

На момент продолжения плана инфраструктурный слой уже частично внедрён:

- `PageId` уже расширен под:
  - `setup-claim`
  - `setup-application`
  - `setup-gigachat`
  - `setup-security`
  - `settings-application`
  - `settings-observability`
  - `settings-gigachat`
  - `settings-security`
  - `settings-history`
  - `files`
  - `batches`
- `gpt2giga/frontend/admin/routes.ts` уже содержит page meta и secondary nav map;
- в `templates.ts` уже есть reusable primitive `renderSubpageNav(...)`;
- server-side shell routes в `gpt2giga/api/admin/ui.py` уже зарегистрированы;
- `pages/index.ts` уже умеет открывать новые page ids;
- integration tests уже проверяют доступность новых HTML routes.

Это значит, что дальше нужен не ещё один routing-first slice, а **доведение page split до реального UX-эффекта**.

---

## Обновлённая оценка состояния по слайсам

### Slice A — routing foundation

Статус: **в основном сделано**.

Что считать уже закрытым:

- новые console routes заведены;
- child pages доступны сервером;
- shared subpage navigation внедрена;
- setup/settings/files-batches уже переведены на multi-page route map;
- тесты на доступность основных HTML entrypoints уже есть.

Что ещё может остаться точечно:

- проверить, нет ли пропущенных compatibility redirects/normalization rules;
- проверить shell behavior для прямого захода на child routes;
- проверить, что left rail и hero не теряют активное состояние на новых страницах.

### Slice B — Setup split

Статус: **в основном сделано**.

По коду уже видно:

- `setup` стал hub page;
- `setup-claim`, `setup-application`, `setup-gigachat`, `setup-security` уже рендерятся отдельно;
- есть secondary nav и переход к next recommended step.

Остаточные задачи:

- сократить второстепенный текст на child pages, если они всё ещё визуально тяжёлые;
- проверить, не дублируются ли одни и те же summary-блоки между hub и focused pages;
- убедиться, что observability handoff остаётся вторичным и не возвращает перегрузку.

### Slice C — Settings split

Статус: **в основном сделано**.

По коду уже видно:

- `settings` стал summary-first hub;
- `settings-application`, `settings-observability`, `settings-gigachat`, `settings-security`, `settings-history` уже выделены;
- история и rollback уже разведены от form-heavy экранов.

Остаточные задачи:

- добить compatibility behavior для старых `?section=` сценариев, если где-то ещё есть UX-рассинхрон;
- проверить, что section pages не тянут лишние блоки из hub;
- проверить ширину form-centric layouts и плотность diagnostic cards.

### Slice D — Files & Batches split

Статус: **заведён route-level split, но UX split ещё не завершён**.

Это сейчас главный незавершённый кусок.

По текущему коду видно:

- `/admin/files-batches`, `/admin/files`, `/admin/batches` уже существуют;
- secondary nav уже есть;
- но `render-files-batches.ts` всё ещё рендерит общий workbench и прямо говорит, что split продолжается.

Именно здесь нужен следующий полноценный инженерный слайс.

---

## Следующий приоритетный план выполнения

### Phase 4A — завершить реальный split Files / Batches

Цель: сделать так, чтобы новые URL отличались не только заголовком и nav, но и **содержанием страницы**.

#### Что сделать

- оставить `/admin/files-batches` как hub/workbench summary;
- сделать `/admin/files` file-first страницей:
  - upload;
  - file inventory;
  - preview/content;
  - минимально нужные actions по выбранному file;
- сделать `/admin/batches` batch-first страницей:
  - batch creation;
  - batch inventory;
  - output/result workflow;
  - минимально нужные actions по выбранному batch.

#### Как разрезать код

- в `gpt2giga/frontend/admin/pages/files-batches/view.ts` выделить:
  - hub renderer;
  - files renderer;
  - batches renderer;
- оставить общие data loaders, serializers и bindings только там, где реально есть shared behavior;
- если bindings стали слишком условными, разделить на:
  - shared bindings;
  - files-only bindings;
  - batches-only bindings.

#### На что смотреть в UX

- на `/admin/files` upload должен быть ближе к верхней части страницы;
- на `/admin/files` preview не должен конкурировать с batch lifecycle;
- на `/admin/batches` создание batch и status/result workflow должны быть видимы без file-upload шума;
- raw metadata/content оставить за `details` или secondary disclosure.

#### Проверка slice

```bash
npm run build:admin
uv run pytest tests/integration/app/test_admin_console_settings.py -q
uv run ruff check .
uv run ruff format --check .
```

Отдельный commit.

### Phase 4B — добить URL/state contract для Files / Batches

После визуального split закрепить предсказуемый state contract.

#### Что сделать

- определить, какие query params остаются общими, а какие должны быть page-specific;
- для `/admin/files` оставить только file-centric filters/selection;
- для `/admin/batches` оставить только batch-centric filters/selection;
- если есть shared selection model, сделать явное правило приоритета:
  - URL;
  - затем UI selection;
  - затем fallback inventory state.

#### Зачем это нужно

Без этого новые страницы будут казаться отдельными только визуально, но не семантически.

#### Проверка slice

- открыть `/admin/files` напрямую с query params;
- открыть `/admin/batches` напрямую с query params;
- проверить browser back/forward;
- проверить refresh без потери ожидаемого selection state.

При необходимости добавить targeted tests на serializer/query behavior.

Отдельный commit.

### Phase 5 — visual density and responsive pass

После завершения реального page split сделать отдельный, уже более безопасный visual slice.

#### Главные задачи

- сузить form-centric content column;
- уменьшить количество full-width forms там, где это не нужно;
- выровнять spacing между hero, subpage nav, summary cards и forms;
- уменьшить давление длинных diagnostics block;
- раньше переводить сложные grids в одну колонку.

#### Где смотреть в первую очередь

- `console.css` после rebuild из source;
- shared templates/layout helpers;
- Setup child pages;
- Settings child pages;
- новые `/admin/files` и `/admin/batches`.

#### Что считать успехом

- на laptop-width формы читаются без ощущения «слишком широко»;
- secondary nav не ломает layout;
- summary cards не спорят по важности с главной формой;
- большие code/json blocks визуально вторичны.

#### Проверка slice

```bash
npm run build:admin
uv run ruff check .
uv run ruff format --check .
```

Если будут UI snapshot/integration tests для shell assets, прогнать и их.

Отдельный commit.

### Phase 6 — optional Traffic split

Эта фаза нужна только после того, как `Files / Batches` и visual pass уже доведены.

#### Что делать только при наличии чистого окна

- оставить `/admin/traffic` summary-first;
- при необходимости добавить:
  - `/admin/traffic-requests`
  - `/admin/traffic-errors`
  - `/admin/traffic-usage`
- использовать тот же reusable subpage nav pattern.

#### Критерий запуска этой фазы

Не начинать её, если:

- `files` / `batches` ещё фактически не разделены;
- form-centric layouts всё ещё перегружены;
- базовые admin route tests не закрывают уже внесённые изменения.

Отдельный commit.

---

## Технические риски и как их сдерживать

### 1. Псевдо-split вместо настоящего split

Риск:

- новые URL есть, но разные страницы по факту показывают одну и ту же тяжёлую поверхность.

Что делать:

- резать view и bindings по смыслу;
- не оставлять весь старый workbench на `files` и `batches`;
- hub page держать summary-first.

### 2. Слишком много shared helpers с ветвлением по page id

Риск:

- вместо упрощения получится общий модуль с большим числом `if (page === ...)`.

Что делать:

- shared оставлять только для реальной общей логики;
- page-local renderers и bindings держать тонкими, но отдельными;
- если условные ветки перевешивают, разносить по модулям.

### 3. Случайная регрессия deep-link behavior

Риск:

- прямые URL, refresh или browser back начнут вести себя непредсказуемо.

Что делать:

- отдельно тестировать прямой заход на каждую child page;
- отдельно тестировать query-param restoration;
- не смешивать page routing и transient UI state без явного serializer contract.

### 4. Визуальная чистка превратится в redesign

Риск:

- много косметических правок при слабом архитектурном выигрыше.

Что делать:

- сначала завершить page split;
- только потом отдельным слайсом править плотность и layout;
- не трогать shell и rail шире, чем это нужно для читаемости.

---

## Что имеет смысл добавить в тестовый план

Помимо уже существующих route tests, полезно добавить или проверить следующее.

### HTML and shell routing

- прямой GET на `/admin/files` возвращает shell;
- прямой GET на `/admin/batches` возвращает shell;
- прямой GET на child pages setup/settings продолжает возвращать shell;
- актив не ломается при новых page-local модулях.

### Compatibility behavior

- `/admin/settings?section=application` переводит в ожидаемую child page semantics;
- `/admin/settings?section=history` не оставляет пользователя на перегруженном hub;
- при наличии legacy links старые entrypoints продолжают работать.

### Asset surface

- если после split появятся новые page-local bundles или дополнительные imports, они реально раздаются из `/admin/assets/admin/...`;
- build не забывает положить их в `packages/gpt2giga-ui/src/gpt2giga_ui/static/admin/`.

### Query/state behavior

- file-centric query params не мешают batch-centric page;
- batch-centric query params не загромождают file page;
- refresh и back/forward сохраняют ожидаемую страницу и состояние фильтров.

---

## Практический stop condition

Работу можно считать законченной без optional Traffic split, если выполнено всё ниже:

- `Setup` и `Settings` действительно работают как hub + focused child pages;
- `Files & Batches` реально разделён на:
  - summary hub;
  - file-first page;
  - batch-first page;
- новые URL отличаются не только nav, но и содержанием;
- form-centric страницы стали уже и спокойнее;
- прямой заход, refresh и back/forward работают предсказуемо;
- ассеты пересобраны;
- admin route tests и релевантные integration tests зелёные.

Если всё это сделано чисто, optional `Traffic` split можно либо взять отдельным следующим циклом, либо оставить как stretch без блокировки merge.
