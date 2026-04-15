# COOL_UI.md

## Что это теперь

`/admin` больше не должен мыслиться как один большой HTML-файл с инлайновым CSS и JS.
Текущее направление правильное:

- сервер отдаёт тонкий shell
- UI живёт в TypeScript-модулях
- браузер грузит ассеты из `/admin/assets/admin/*`
- страницы внутри console переиспользуют общий layout, API client, helpers и page renderers

То есть `gpt2giga Console` теперь надо развивать как **небольшой встроенный admin frontend**, а не как “ещё один template”.

## Актуальная структура

Исходники UI:

- [gpt2giga/frontend/admin/api.ts](./gpt2giga/frontend/admin/api.ts)
- [gpt2giga/frontend/admin/app.ts](./gpt2giga/frontend/admin/app.ts)
- [gpt2giga/frontend/admin/forms.ts](./gpt2giga/frontend/admin/forms.ts)
- [gpt2giga/frontend/admin/routes.ts](./gpt2giga/frontend/admin/routes.ts)
- [gpt2giga/frontend/admin/templates.ts](./gpt2giga/frontend/admin/templates.ts)
- [gpt2giga/frontend/admin/pages/](./gpt2giga/frontend/admin/pages)

Runtime-ассеты:

- [packages/gpt2giga-ui/src/gpt2giga_ui/static/admin/](./packages/gpt2giga-ui/src/gpt2giga_ui/static/admin)

Shell:

- [packages/gpt2giga-ui/src/gpt2giga_ui/templates/console.html](./packages/gpt2giga-ui/src/gpt2giga_ui/templates/console.html)

Раздача статики:

- [gpt2giga/app/factory.py](./gpt2giga/app/factory.py)

Роутинг shell:

- [gpt2giga/api/admin/ui.py](./gpt2giga/api/admin/ui.py)

## Продуктовая цель

Сделать из `/admin` нормальную operator console для:

- first-run setup
- persisted config management
- GigaChat credentials management
- gateway/admin key workflows
- logs и runtime diagnostics
- traffic/usage observability
- playground для ручных запросов
- files и batches operator workflows

Ориентир по UX:

- не public dashboard
- не generic SaaS admin
- не “debug page”
- локальный control plane для FastAPI proxy

## Ключевые UX-принципы

### 1. Control plane отдельно от data plane

Console должна явно разделять:

- admin/control-plane API: `/admin/api/*`
- gateway/data-plane API: `/v1/*`, `/v1beta/*`, `/messages`, `/models` и т.д.

Это уже отражено в UI:

- отдельный admin key / bootstrap token
- отдельный gateway API key

Дальше это разделение надо только усиливать.

### 2. Shell тонкий, страницы модульные

Нельзя возвращаться к паттерну “2-3 тысячи строк в одном template”.

Любой следующий UI-change должен по умолчанию идти в:

- `frontend/admin/pages/*`
- общие helpers в `api.ts`, `templates.ts`, `forms.ts`, `utils.ts`

Если новая фича не помещается в существующий page renderer, значит нужен ещё один модуль, а не новый монолит.

### 3. TypeScript first

Frontend уже переведён на TypeScript. Это нужно сохранить.

Правило:

- редактируем `.ts` в `gpt2giga/frontend/admin`
- собираем в `packages/gpt2giga-ui/src/gpt2giga_ui/static/admin`
- shell только подключает готовые файлы

### 4. Bootstrap без `.env`

Главный пользовательский сценарий по-прежнему такой:

```bash
docker compose up -d
open http://localhost:8090
```

После этого оператор должен уметь:

- зайти в console
- пройти setup
- сохранить конфиг
- создать ключи
- протестировать прокси

без ручной правки `.env`.

## Информационная архитектура console

Текущий набор страниц правильный и его стоит считать базовым:

- `Overview`
- `Setup`
- `Settings`
- `API Keys`
- `Logs`
- `Playground`
- `Traffic`
- `Providers`
- `Files & Batches`
- `System`

Это не “табы для красоты”. Это реальные operator workflows.

## Что уже хорошо в текущем frontend-подходе

### Overview

Должен оставаться executive-summary экраном:

- setup readiness
- runtime posture
- recent errors
- usage summaries

### Setup

Должен оставаться guided first-run страницей:

- claim instance
- application posture
- GigaChat auth
- security bootstrap
- finish state

### Settings

Это не просто форма, а config editor:

- 3 логических секции
- pending diff
- revisions
- rollback

### Keys

Отдельная страница для ключей была правильным решением.
Не надо обратно смешивать её с `Settings`.

### Logs

Нужна как отдельная рабочая поверхность, а не как маленький блок на overview.

### Playground

Нужен как встроенный smoke client.
Он особенно важен в zero-env/bootstrap сценарии.

### Files & Batches

Это уже не “nice to have”, а полезный operator surface.
Его надо развивать дальше, а не прятать.

## Что доведено после параллельной волны

Backlog из [UI_PARALLEL_TASKS.md](./UI_PARALLEL_TASKS.md) закрыт целиком, включая интеграционные `T6-T7`.
Это значит, что console теперь прошла не только этап modular TypeScript migration, но и отдельный проход по зрелости operator workflows.

### 1. Shared primitives и page structure

То, что раньше было намечено как следующий шаг, теперь уже считается базовым состоянием:

- в `templates.ts` и связанных helper-модулях вынесены reusable summary/table/inspector blocks
- самые тяжёлые page renderers стали короче и меньше завязаны на одноразовые HTML-строки
- общие state/pending/selection patterns больше не размазаны случайно по страницам

Именно это состояние теперь нужно сохранять: новые UI-изменения должны сначала ложиться в page-local код, а повторяющиеся части должны осознанно попадать в shared primitives.

### 2. Logs и Traffic работают как единый workflow

Связка `Logs` + `Traffic` больше не выглядит как две соседние debug-страницы:

- `Logs` даёт operator-oriented filters, live stream status, cleanup и request/error context рядом с tail surface
- `request_id` handoff работает в обе стороны без ручного копирования фильтров
- `Traffic` показывает KPI, recent events и usage inspectors в summary-first виде, а не как raw JSON-only presentation

То есть console уже поддерживает нормальный путь: увидеть событие, pin нужный запрос, открыть structured context и перейти в соседнюю рабочую поверхность без потери состояния.

### 3. Files & Batches стал полноценной operator surface

Страница `Files & Batches` теперь закрывает не только базовый просмотр:

- есть явные pending/disabled states вокруг upload/create/delete/load действий
- selection-driven inspector даёт action rail и summary до открытия raw payload
- preview/output flow даёт читаемый format/size/context summary и доводит оператора до batch handoff

Эта страница теперь должна восприниматься как рабочий lifecycle UI, а не как витрина для JSON-объектов.

### 4. Setup и Settings читаются как управляемые формы

Формы доведены до более понятного operator UX:

- inline validation и busy-state снимают двусмысленность во время save/test/rollback
- change summary явно разделяет `applies live` и `restart after save`
- secret updates показываются как отдельный тип изменения, а не теряются внутри общего diff
- persisted state и runtime-applied impact читаются как разные вещи

Для control plane это важнее визуального слоя: оператор должен понимать не только что меняется, но и когда это реально вступит в силу.

### 5. Overview, Providers, System и Playground больше не сырой diagnostics слой

После завершения параллельной волны:

- `Overview` стал сильнее как executive-summary экран
- `Providers` показывает capability matrix, backend posture и provider detail surfaces
- `System` даёт route/runtime/config summaries с первого экрана, а полный JSON оставляет как inspection surface
- `Playground` имеет более внятный request/stream lifecycle и ощущается как встроенный smoke client, а не как случайная debug-форма

Именно такая подача нужна для локального control plane: summary-first, с понятными handoff-ссылками в более глубокие workflow.

### 6. Build step закреплён как часть UI workflow

Фронтенд теперь окончательно живёт по схеме:

```bash
npm run build:admin
```

Скомпилированные ассеты в `packages/gpt2giga-ui/src/gpt2giga_ui/static/admin/` обновляются как часть финальной интеграции, а не как побочный эффект случайной локальной сборки.

## Чего делать не надо

- Не возвращать инлайновый JS в `console.html`.
- Не складывать новые страницы обратно в один giant renderer.
- Не плодить альтернативные UI-entrypoints без причины.
- Не дублировать одно и то же поведение одновременно в shell и в TS.
- Не тащить тяжёлый frontend stack без явной необходимости.

## Практическое правило для следующих изменений

Если меняется admin UI:

1. правим `gpt2giga/frontend/admin/*.ts`
2. при необходимости правим shell/styling в `packages/gpt2giga-ui/src/gpt2giga_ui/`
3. запускаем `npm run build:admin`
4. прогоняем admin integration tests

Если изменение не требует нового backend API, его не надо проталкивать через template-хак.

## В чём сейчас настоящая “coolness”

Не в визуальном декоративном слое как таковом, а в том, что console стала:

- структурированной
- поддерживаемой
- TypeScript-based
- совместимой с текущим FastAPI backend
- пригодной для дальнейшей эволюции

Именно это состояние надо сохранить и развивать.
