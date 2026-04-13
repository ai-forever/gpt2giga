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

- [gpt2giga/frontend/admin/api.ts](/Users/riyakupov/code_projects/gpt2giga/gpt2giga/frontend/admin/api.ts)
- [gpt2giga/frontend/admin/app.ts](/Users/riyakupov/code_projects/gpt2giga/gpt2giga/frontend/admin/app.ts)
- [gpt2giga/frontend/admin/forms.ts](/Users/riyakupov/code_projects/gpt2giga/gpt2giga/frontend/admin/forms.ts)
- [gpt2giga/frontend/admin/routes.ts](/Users/riyakupov/code_projects/gpt2giga/gpt2giga/frontend/admin/routes.ts)
- [gpt2giga/frontend/admin/templates.ts](/Users/riyakupov/code_projects/gpt2giga/gpt2giga/frontend/admin/templates.ts)
- [gpt2giga/frontend/admin/pages/](/Users/riyakupov/code_projects/gpt2giga/gpt2giga/frontend/admin/pages)

Скомпилированные ассеты:

- [gpt2giga/static/admin/](/Users/riyakupov/code_projects/gpt2giga/gpt2giga/static/admin)

Shell:

- [gpt2giga/templates/console.html](/Users/riyakupov/code_projects/gpt2giga/gpt2giga/templates/console.html)
- [gpt2giga/templates/admin.html](/Users/riyakupov/code_projects/gpt2giga/gpt2giga/templates/admin.html)

Раздача статики:

- [gpt2giga/app/factory.py](/Users/riyakupov/code_projects/gpt2giga/gpt2giga/app/factory.py)

Роутинг shell:

- [gpt2giga/api/admin/ui.py](/Users/riyakupov/code_projects/gpt2giga/gpt2giga/api/admin/ui.py)

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
- собираем в `gpt2giga/static/admin`
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

## Следующий уровень качества для UI

### 1. Сильнее отделить layout от page logic

Сейчас уже есть хороший первый шаг:

- общий `AdminApp`
- page registry
- page renderers

Следующий шаг:

- более явные reusable view primitives
- меньше ручной HTML-строки в page renderers
- отдельные small render helpers для tables/forms/inspectors

Последний проход уже двинул это в нужную сторону:

- в `templates.ts` появился ещё один reusable summary/inspector primitive вместо page-local ad-hoc блоков
- `Logs` и `Files & Batches` начали использовать summary-first surfaces, а не только raw JSON `pre`

### 2. Нормализовать page state

Сейчас state mostly локальный по страницам, что нормально для MVP.
Но дальше полезно добавить более явные паттерны для:

- loading state
- action pending state
- optimistic UI / rerender
- cleanup для stream/subscription flows

Особенно важно для `Logs`, `Playground`, `Files & Batches`.

После последнего шага:

- у `Logs` уже есть явный lifecycle для live stream state и cleanup
- у `Files & Batches` уже есть локальный inventory filter state через URL/query-driven rerender

Следующий уровень тут всё ещё нужен для более системных pending/optimistic patterns.

### 3. Улучшить logs и traffic workflows

Ближайшие UI-улучшения высокого сигнала:

- deeper linking request/error/log contexts
- better traffic summaries вместо raw JSON everywhere
- richer files/batches lifecycle actions и preview ergonomics

Часть этого уже сделана:

- `Logs` теперь имеет filters, live stream status и нормальный SSE parsing без протокольного шума в `pre`
- `Logs` теперь умеет инспектировать recent request/error context рядом с tail surface
- `Files & Batches` теперь имеет inventory filters и более читаемый inspector summary

### 4. Улучшить forms UX

Нужны:

- inline validation
- disable buttons during submit
- clearer restart-required messaging
- better handling для secret fields
- более явное разделение persisted vs runtime-applied state

### 5. Сделать compile step частью привычного workflow

Новый фронтенд теперь имеет build step:

```bash
npm run build:admin
```

Это нужно считать обязательной частью UI-изменений.

## Чего делать не надо

- Не возвращать инлайновый JS в `console.html`.
- Не складывать новые страницы обратно в один giant renderer.
- Не плодить альтернативные UI-entrypoints без причины.
- Не дублировать одно и то же поведение одновременно в shell и в TS.
- Не тащить тяжёлый frontend stack без явной необходимости.

## Практическое правило для следующих изменений

Если меняется admin UI:

1. правим `gpt2giga/frontend/admin/*.ts`
2. при необходимости правим shell/styling/static mount
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
