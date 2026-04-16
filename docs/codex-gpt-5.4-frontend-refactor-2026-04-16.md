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
