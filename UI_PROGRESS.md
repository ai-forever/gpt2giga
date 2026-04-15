# UI_PROGRESS.md

## Текущий статус

Admin frontend больше не живёт в одном огромном template.
После последнего рефакторинга `/admin` переведён на модульный TypeScript frontend с раздачей статических ассетов из приложения.

Это главный сдвиг по сравнению с предыдущим состоянием.

Дополнительно после следующего шага UI-полировки:

- `Traffic` перестал быть просто четырьмя JSON-блоками и получил operator-oriented filters, KPI summary, таблицы recent events и usage inspectors
- `Providers` получил capability matrix, backend posture, provider detail surface и route inventory filter вместо raw JSON-only presentation
- `System` теперь показывает setup/runtime/config/route posture как читаемые summary sections, а полный diagnostics JSON остался как export/inspection surface
- в shared frontend helpers появились более мелкие reusable table/stat primitives, чтобы не раздувать page renderers одноразовой HTML-строкой
- `Logs` получил operator-oriented filter bar, явное live stream state, SSE parsing без сырых `event:/data:` хвостов и context inspector на основе recent request/error feeds
- `Logs` и `Traffic` теперь связаны через `request_id`: recent event surfaces умеют pin конкретного запроса, а inspector даёт точечный handoff между log context и traffic context без ручного копирования фильтров
- `Files & Batches` получил inventory filters и summary-first inspector, чтобы рабочая поверхность не сводилась к raw JSON-only просмотру
- `Files & Batches` получил context-aware inspector actions, preview summaries для input/output content и явные pending states вокруг upload/create/delete/load операций
- `Setup` и `Settings` получили более явный save impact summary: теперь форма показывает, что применится live, что потребует restart, и какие secret surfaces будут затронуты, а busy state во время submit/test/rollback виден на всей рабочей секции

## Что теперь является источником правды

### Shell и роутинг

- [gpt2giga/templates/console.html](/Users/riyakupov/code_projects/gpt2giga/gpt2giga/templates/console.html)
- [gpt2giga/templates/admin.html](/Users/riyakupov/code_projects/gpt2giga/gpt2giga/templates/admin.html)
- [gpt2giga/api/admin/ui.py](/Users/riyakupov/code_projects/gpt2giga/gpt2giga/api/admin/ui.py)

Что изменилось:

- `console.html` стал thin shell
- `admin.html` теперь legacy shell/redirect, а не отдельный боевой UI
- все `/admin/*` страницы продолжают обслуживаться тем же shell

### Frontend source

- [gpt2giga/frontend/admin/app.ts](/Users/riyakupov/code_projects/gpt2giga/gpt2giga/frontend/admin/app.ts)
- [gpt2giga/frontend/admin/api.ts](/Users/riyakupov/code_projects/gpt2giga/gpt2giga/frontend/admin/api.ts)
- [gpt2giga/frontend/admin/forms.ts](/Users/riyakupov/code_projects/gpt2giga/gpt2giga/frontend/admin/forms.ts)
- [gpt2giga/frontend/admin/routes.ts](/Users/riyakupov/code_projects/gpt2giga/gpt2giga/frontend/admin/routes.ts)
- [gpt2giga/frontend/admin/templates.ts](/Users/riyakupov/code_projects/gpt2giga/gpt2giga/frontend/admin/templates.ts)
- [gpt2giga/frontend/admin/utils.ts](/Users/riyakupov/code_projects/gpt2giga/gpt2giga/frontend/admin/utils.ts)
- [gpt2giga/frontend/admin/pages/](/Users/riyakupov/code_projects/gpt2giga/gpt2giga/frontend/admin/pages)

Что появилось:

- общий `AdminApp`
- единый client для admin/gateway запросов
- page registry
- отдельные page renderers
- shared helpers для форм, шаблонов и утилит

### Static assets

- [gpt2giga/static/admin/](/Users/riyakupov/code_projects/gpt2giga/gpt2giga/static/admin)
- [gpt2giga/static/admin/console.css](/Users/riyakupov/code_projects/gpt2giga/gpt2giga/static/admin/console.css)
- [gpt2giga/static/admin/index.js](/Users/riyakupov/code_projects/gpt2giga/gpt2giga/static/admin/index.js)

Что изменилось:

- браузер теперь грузит UI как нормальные статические ассеты
- compiled JS хранится рядом с приложением
- routing shell больше не держит в себе весь frontend runtime

### Build step

Добавлено:

- [package.json](/Users/riyakupov/code_projects/gpt2giga/package.json)
- [package-lock.json](/Users/riyakupov/code_projects/gpt2giga/package-lock.json)
- [tsconfig.json](/Users/riyakupov/code_projects/gpt2giga/tsconfig.json)

Текущий build command:

```bash
npm run build:admin
```

### Раздача ассетов из FastAPI

- [gpt2giga/app/factory.py](/Users/riyakupov/code_projects/gpt2giga/gpt2giga/app/factory.py)

Что сделано:

- подключён `StaticFiles`
- ассеты доступны по `/admin/assets/*`

## Что реально покрыто в UI сейчас

Отдельные page renderers есть для:

- `Overview`
- `Setup`
- `Settings`
- `Keys`
- `Logs`
- `Playground`
- `Traffic`
- `Providers`
- `Files & Batches`
- `System`

То есть старая функциональность монолитного `console.html` не потеряна, а перенесена в модульную структуру.

## Что осталось из backend-части и продолжает работать

### Control plane / setup / settings

Актуальные файлы:

- [gpt2giga/core/config/control_plane.py](/Users/riyakupov/code_projects/gpt2giga/gpt2giga/core/config/control_plane.py)
- [gpt2giga/api/admin/settings.py](/Users/riyakupov/code_projects/gpt2giga/gpt2giga/api/admin/settings.py)
- [gpt2giga/api/admin/access.py](/Users/riyakupov/code_projects/gpt2giga/gpt2giga/api/admin/access.py)

Что уже есть:

- persisted control-plane config
- bootstrap token flow
- claim instance
- split settings API
- revisions + rollback
- GigaChat connection test
- key management

### Runtime / observability / metadata

- [gpt2giga/api/admin/runtime.py](/Users/riyakupov/code_projects/gpt2giga/gpt2giga/api/admin/runtime.py)
- [gpt2giga/api/admin/logs.py](/Users/riyakupov/code_projects/gpt2giga/gpt2giga/api/admin/logs.py)

Что уже есть:

- runtime summary
- capabilities
- routes
- requests/errors recent feeds
- usage by key/provider
- logs tail и stream

## Что стало лучше после TS-рефакторинга

### 1. Исчезла зависимость от giant template

Раньше почти весь frontend был заперт в:

- одном HTML
- одном CSS blob
- одном JS blob

Сейчас код уже можно нормально сопровождать.

### 2. Появилась нормальная точка входа для UI-изменений

Теперь изменение страницы делается в конкретном модуле, а не в середине giant `script` tag.

### 3. Появился явный build pipeline

Теперь у admin frontend есть предсказуемый compile step.
Это важная разница по сравнению с предыдущим ad-hoc подходом.

### 4. Shell стал стабильным

HTML shell теперь почти не должен меняться при каждом UI-изменении.
Это хороший признак.

## Что закрыто в параллельной волне

Backlog из [UI_PARALLEL_TASKS.md](/Users/riyakupov/code_projects/gpt2giga/UI_PARALLEL_TASKS.md) считается завершённым полностью.
То есть закрыты и feature-потоки `T1-T5`, и интеграционные задачи `T6-T7`.

### T1. Logs + Traffic

Закрыто:

- `Logs` и `Traffic` теперь работают вокруг одного `request_id` handoff
- live stream lifecycle и cleanup выражены явно, без висящих подписок и сырого SSE-шумa
- request/error context и traffic event surfaces связаны взаимными handoff-ссылками
- `Traffic` показывает KPI, recent events и usage inspectors как operator surfaces, а не как набор JSON-блоков

### T2. Files & Batches

Закрыто:

- batch/file actions имеют явные pending/disabled states
- selection -> inspect -> preview/output flow стал непрерывным operator workflow
- inspector показывает summary-first контекст до открытия raw payload
- batch lifecycle actions и handoff между связанными сущностями вынесены в action rail

### T3. Setup + Settings UX

Закрыто:

- inline validation и busy-state покрывают save/test/rollback сценарии
- форма явно делит изменения на `applies live` и `restart after save`
- secret field updates читаются как отдельная masked-change группа
- persisted state и runtime-applied impact больше не смешиваются визуально

### T4. Providers + System + Overview

Закрыто:

- `Overview` доведён до executive-summary экрана
- `Providers` показывает capability matrix, backend posture и provider detail surface
- `System` показывает route/runtime/config summaries без упора в raw JSON
- между summary surfaces и рабочими страницами есть понятные handoff-ссылки там, где они уместны

### T5. Playground

Закрыто:

- request/stream lifecycle больше не оставляет UI в подвешенном состоянии
- pending/error/output presentation стала понятнее для ручного smoke flow
- zero-env/bootstrap сценарий ощущается как встроенный операторский клиент, а не как вспомогательная debug-форма

### T6. Shared UI primitives и state patterns

Закрыто:

- повторяющиеся summary/table/form/inspector blocks вынесены в reusable primitives
- тяжёлые page renderers стали меньше и читаемее
- общие loading/busy/selection/state helpers нормализованы на уровне shared frontend-кода

### T7. Build, compiled assets и интеграционная проверка

Закрыто:

- admin frontend централизованно собран
- committed static assets синхронизированы с текущим TypeScript source
- финальная интеграция проверена после merge feature-потоков

## Что теперь считается базовым состоянием UI

После завершения параллельной волны `/admin` больше не только модульный TS frontend, но и более зрелая operator console:

- summary-first presentation закреплена на `Overview`, `Traffic`, `Providers`, `System`, `Files & Batches`
- связанные страницы переходят друг в друга через осмысленные handoff-сценарии, а не через ручной перенос фильтров
- shared primitives и state patterns вынесены из page-local ad-hoc логики
- build step и обновление compiled assets считаются обязательной частью финальной интеграции

## Что проверено в финальной интеграции

Финальный проход для закрытия `T7` опирается на обязательный набор проверок из task breakdown:

- `npm run build:admin`
- `uv run ruff check .`
- `uv run ruff format --check .`
- `uv run pytest tests/`

Дополнительно в этом состоянии считаются закрытыми проверки на:

- shell routes `/admin/*`
- раздачу `/admin/assets/admin/index.js`
- новые operator UI surfaces для `Logs`, `Traffic`, `Files & Batches`, `Providers`, `System`, `Overview`, `Playground`
- `request_id` contract и handoff между `Logs` и `Traffic`
- form UX проход для `Setup` и `Settings`

## Что логично делать дальше

Следующая волна, если она понадобится, уже не про закрытие старого UI backlog, а про новый уровень требований.
То есть дальнейшие задачи нужно формулировать как отдельный roadmap, а не как хвост незавершённого TS-рефакторинга.
