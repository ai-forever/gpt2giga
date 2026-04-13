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
- `Files & Batches` получил inventory filters и summary-first inspector, чтобы рабочая поверхность не сводилась к raw JSON-only просмотру

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

## Что ещё не доведено

### 1. HTML generation внутри page renderers всё ещё строковая

Даже после перехода на TS часть страниц всё ещё рендерится через большие HTML-строки.
Это уже лучше, чем один giant template, но до идеального состояния ещё есть путь.

Что логично делать дальше:

- выносить table/form fragments в маленькие reusable render helpers
- уменьшать размер отдельных page renderers
- постепенно убирать дублирование между filter/inspector паттернами в `Traffic`, `Logs` и `Files & Batches`

### 2. Нет более строгой модели UI state

Сейчас page-level state mostly локальный и императивный.
Для текущего размера это терпимо, но для `Logs`, `Files & Batches`, `Playground` и `Settings` со временем станет узким местом.

### 3. Не все operator workflows визуально одинаково зрелые

Лучше всего сейчас выглядят:

- setup/settings
- keys
- basic logs/playground/files-batches flow

Зонами, где ещё есть запас по UX, остаются:

- logs
- files & batches inspector
- parts of setup/settings pending-state UX

После последнего прохода `logs` и `files & batches` уже заметно вышли из состояния “минимально рабочая поверхность”, но там всё ещё есть запас по:

- более плотной связке log lines с request ids и traffic detail
- richer batch lifecycle actions и output preview ergonomics
- более явным pending/disabled states вокруг долгих операций

Самые слабые страницы `traffic/providers/system` уже выведены из состояния “raw JSON viewer” в более читаемые operator surfaces.

### 4. Build artifacts хранятся в репозитории

Это осознанный текущий компромисс, но это всё равно нужно помнить.
Если подход менять, то менять уже системно, а не полумерами.

## Что логично делать следующим

1. Продолжить разбирать самые тяжёлые page renderers на ещё более мелкие UI-блоки.
2. Продолжить усиливать `Logs`: richer linking между log lines и traffic/request context, более явные stream diagnostics.
3. Улучшить формы в `Setup` и `Settings`: disabled/pending states, validation, clearer restart messaging.
4. Продолжить улучшать `Files & Batches`: richer batch workflows, preview ergonomics, lifecycle actions.
5. Решить, хотим ли мы дальше жить на “TS -> committed JS assets” или когда-нибудь переходить на более формализованный frontend toolchain.

## Что проверено после перехода на TypeScript

Проходят:

- `npm run build:admin`
- `uv run ruff check .`
- `uv run ruff format --check .`
- `uv run pytest tests/integration/app/test_admin_console_settings.py tests/integration/app/test_api_server.py tests/integration/app/test_system_router_extra.py`

Также проходят отдельные проверки на:

- shell routes `/admin/*`
- раздачу `/admin/assets/admin/index.js`
- новый контракт admin shell, где предупреждения рендерятся клиентом, а не лежат статически в HTML
- свежие operator UI обновления для `Traffic`, `Providers` и `System`
- свежие operator UI обновления для `Logs` и `Files & Batches`

## Что не прошло в полном test suite на момент обновления

Полный запуск:

```bash
uv run pytest tests/ --cov=. --cov-report=term --cov-fail-under=80
```

всё ещё падает, но оставшиеся кейсы не относятся напрямую к TS-рефакторингу admin frontend:

- `tests/integration/openai/test_router_stream_chat.py::test_chat_completions_stream_records_audit_metadata`
- `tests/smoke/test_ci_smoke.py::test_ci_smoke_openai_chat`
- `tests/smoke/test_ci_smoke.py::test_ci_smoke_anthropic_messages`
- `tests/smoke/test_ci_smoke.py::test_ci_smoke_gemini_generate_content`
- `tests/smoke/test_starlette_1_smoke.py::test_starlette_1_openai_streaming_smoke`
- `tests/unit/providers/test_registry.py::test_gemini_provider_descriptor_uses_gemini_auth_policy`

Из наблюдаемого:

- часть streaming/smoke падений сейчас связана с ожиданием старого dict-like поведения у fake chat mapper input
- один unit test по provider registry расходится с текущим числом gemini mounts

Это отдельный кусок работы, не про admin UI.
