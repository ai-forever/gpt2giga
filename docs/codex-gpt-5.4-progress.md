# Прогресс по плану Codex gpt-5.4

Дата старта: 2026-04-15
План: [codex-gpt-5.4-plan-2026-04-15.md](./codex-gpt-5.4-plan-2026-04-15.md)
Обязательно: после сделано нужно закоммитить изменения.

## Phase 0

### Сделано

- Проверил исходный drift admin UI: `npm run build:admin` писал в `gpt2giga/static/admin`, а runtime грузил shell и статику из optional package `gpt2giga_ui`.
- Подтвердил фактическое расхождение между двумя деревьями shipped asset-ов:
  - `gpt2giga/static/admin/forms.js`
  - `gpt2giga/static/admin/pages/control-plane-sections.js`
- Перевёл `tsconfig.json` на единый output path: `packages/gpt2giga-ui/src/gpt2giga_ui/static/`.
- Пересобрал admin UI и синхронизировал package assets; после сборки расхождение между деревьями исчезло.
- Удалил root-дубли `gpt2giga/static/admin/*` и `gpt2giga/templates/*`, которые не участвуют в runtime.
- Обновил ключевые docs под реальный packaging/runtime flow:
  - `README.md`
  - `AGENTS.md`
  - `gpt2giga/AGENTS.md`
  - `docs/architecture.md`
  - `COOL_UI.md`
  - `UI_PROGRESS.md`
  - `docs/refactor-tasks-2026-04-14.md`
- Убрал побочный эффект из `gpt2giga/app/cli.py`: `load_config()` больше не оставляет значения из `.env` в `os.environ` после построения `ProxyConfig`.
- Добавил regression test на отсутствие env-leak после `--env-path`, чтобы admin/integration тесты не зависели от локального `.env`.

### Проверка

- `npm run build:admin` проходит и пишет output в `packages/gpt2giga-ui/src/gpt2giga_ui/static/admin/`.
- Точечные admin UI тесты проходят при явном отключении telemetry в окружении:
  - `GPT2GIGA_ENABLE_TELEMETRY=false uv run pytest tests/integration/app/test_api_server.py::test_admin_static_assets_are_served tests/integration/app/test_admin_console_settings.py::test_console_routes_are_available tests/integration/app/test_system_router_extra.py::test_admin_ui_ok tests/integration/app/test_system_router_extra.py::test_admin_ui_warning_banner`
- Расширенный regression прогон теперь стабилен без ручного отключения telemetry:
  - `uv run pytest tests/unit/core/test_cli.py tests/integration/app/test_api_server.py tests/integration/app/test_admin_console_settings.py tests/integration/app/test_system_router_extra.py -q`
- Локализован и закрыт источник нестабильности:
  - `tests/integration/app/test_api_server.py::test_run_server` вызывал `load_config()`;
  - старое поведение `load_config()` подгружало корневой `.env` в процесс навсегда;
  - из-за этого последующие тесты неожиданно наследовали `GPT2GIGA_OBSERVABILITY_SINKS=phoenix`.

### Дальше

- Phase 0 можно считать закрытой: source-of-truth для shipped UI assets зафиксирован, docs синхронизированы, admin/integration verification не зависит от локального `.env`.
- Следующий шаг — Phase 1: выделение observability в отдельную control-plane settings section и API.

## Phase 1

### Сделано

- Добавлен отдельный backend slice для observability settings:
  - typed helper-модели в `gpt2giga/core/config/observability.py`;
  - новый admin endpoint `GET/PUT /admin/api/settings/observability`.
- Сгруппировал observability-конфиг поверх существующих flat `ProxySettings` полей, не ломая текущую совместимость:
  - `enable_telemetry`;
  - `observability_sinks`;
  - OTLP/Langfuse/Phoenix-specific поля.
- Новый endpoint возвращает safe UI-facing payload:
  - `active_sinks`;
  - `metrics_enabled`;
  - sink cards для `prometheus`, `otlp`, `langfuse`, `phoenix`;
  - `configured` / `missing_fields` / `live_apply` / `restart_required`;
  - masked/boolean presentation для secret-полей вместо raw secrets.
- Добавил persistence/update flow для grouped observability payload-ов через существующий control-plane config pipeline.
- Расширил admin settings integration coverage:
  - чтение grouped observability section;
  - запись OTLP/Phoenix настроек;
  - повторное чтение после persist/apply.
- Подключил observability backend slice к admin UI:
  - в `Settings` появился отдельный tab `Observability`;
  - telemetry toggle и sink-конфиг больше не живут внутри общего `application` form в day-2 settings flow.
- Добавил отдельный frontend payload/status flow для observability:
  - `buildObservabilityPayload(...)`;
  - pending diff/status summary для grouped sink payload-ов;
  - replace/clear UX для OTLP headers и Langfuse/Phoenix credential fields.
- UI теперь рендерит sink-specific cards для `prometheus`, `otlp`, `langfuse`, `phoenix` с:
  - enabled/configured статусом;
  - missing fields;
  - live-apply vs restart-safe подсказками;
  - sink-specific form controls.
- Расширил safe observability payload для UI:
  - top-level `otlp`, `langfuse`, `phoenix` sections;
  - masked previews для `langfuse_secret_key` и `phoenix_api_key`.
- Пересобрал shipped admin assets в `packages/gpt2giga-ui/src/gpt2giga_ui/static/admin/`.

### Проверка

- `npm run build:admin`
- `uv run pytest tests/integration/app/test_admin_console_settings.py -q`
- `uv run pytest tests/integration/app/test_system_router_extra.py::test_admin_ui_ok tests/integration/app/test_system_router_extra.py::test_admin_ui_warning_banner -q`
- `uv run pytest tests/unit/core/test_cli.py tests/integration/app/test_api_server.py tests/integration/app/test_admin_console_settings.py tests/integration/app/test_system_router_extra.py -q`
- `uv run ruff check gpt2giga/core/config/observability.py gpt2giga/api/admin/settings.py gpt2giga/app/cli.py tests/integration/app/test_admin_console_settings.py tests/unit/core/test_cli.py`
- `uv run ruff format --check gpt2giga/core/config/observability.py gpt2giga/api/admin/settings.py gpt2giga/app/cli.py tests/integration/app/test_admin_console_settings.py tests/unit/core/test_cli.py`

### Дальше

- Phase 1 по сути закрыта: observability стала first-class частью control plane и в backend, и в operator UI.
- Следующий шаг по плану — Phase 2: начать разрезать `gpt2giga/api/admin/settings.py` и `gpt2giga/api/admin/runtime.py` на domain-oriented services.
- Внутри observability ещё остаётся полезный follow-up, который можно делать уже как часть Phase 2/3:
  - label/description/category;
  - required settings;
  - live-apply vs restart semantics;
  - test/export actions.

## Phase 2

### Сделано

- Начат разрез `gpt2giga/api/admin/runtime.py` на domain-oriented app services.
- Добавлен новый app-level модуль `gpt2giga/app/admin_runtime.py` с двумя явными service-entrypoints:
  - `AdminRuntimeSnapshotService` для version/config/runtime/routes/capabilities/recent-events payload-ов;
  - `AdminUsageReporter` для aggregated usage payload-ов и filter-summary logic.
- Перенёс из route-модуля в service layer:
  - runtime snapshot builders;
  - config summary builders;
  - capability matrix / admin route-capability metadata;
  - recent requests/errors payload assembly;
  - usage filtering, sorting, available-filters и summary aggregation.
- Упростил `gpt2giga/api/admin/runtime.py` до тонкого HTTP слоя:
  - IP allowlist check;
  - query params;
  - вызов соответствующего service builder-а;
  - metrics endpoint оставлен transport-level wrapper-ом над `build_metrics_response(...)`.
- Добавил unit coverage на новый service slice:
  - runtime snapshot payload;
  - grouped config summary payload;
  - usage filtering + summary aggregation.
- Обновил `gpt2giga/AGENTS.md`, чтобы repo map отражал новый app-level service module.
- Продолжил разрез `gpt2giga/api/admin/settings.py` на domain-oriented app services.
- Добавлен новый app-level модуль `gpt2giga/app/admin_settings.py` с двумя явными service-entrypoints:
  - `AdminControlPlaneSettingsService` для setup/status, settings sections, revision diff/rollback и GigaChat test-connection flow;
  - `AdminKeyManagementService` для global/scoped API-key lifecycle и usage-aware key payload-ов.
- Перенёс из route-модуля в service layer:
  - safe settings snapshot builders для `application`, `observability`, `gigachat`, `security`;
  - section-level validate/update/apply/persist pipeline;
  - revision diff, snapshot и rollback logic;
  - GigaChat settings test flow;
  - global/scoped API-key create/rotate/delete и list payload assembly.
- Упростил `gpt2giga/api/admin/settings.py` до thin HTTP слоя:
  - IP allowlist check;
  - request body/query parsing;
  - вызов соответствующего control-plane или key-management service entrypoint-а.
- Добавил unit coverage на новый settings/key-management service slice:
  - observability update payload;
  - masked revision diff for secret fields;
  - direct GigaChat factory test flow;
  - scoped key lifecycle.
- Обновил `gpt2giga/AGENTS.md`, чтобы repo map отражал новый `app/admin_settings.py` и тонкий `api/admin/settings.py`.

### Проверка

- `uv sync --all-extras --dev`
- `uv run ruff check gpt2giga/app/admin_runtime.py gpt2giga/api/admin/runtime.py tests/unit/app/test_admin_runtime.py`
- `uv run ruff format --check gpt2giga/app/admin_runtime.py gpt2giga/api/admin/runtime.py tests/unit/app/test_admin_runtime.py`
- `uv run pytest tests/unit/app/test_admin_runtime.py tests/integration/app/test_system_router_extra.py -q`
- `uv run pytest tests/integration/app/test_api_server.py -q`
- `uv run ruff check gpt2giga/app/admin_settings.py gpt2giga/api/admin/settings.py tests/unit/app/test_admin_settings.py`
- `uv run ruff format --check gpt2giga/app/admin_settings.py gpt2giga/api/admin/settings.py tests/unit/app/test_admin_settings.py`
- `uv run pytest tests/unit/app/test_admin_settings.py tests/unit/app/test_admin_runtime.py -q`
- `uv run pytest tests/integration/app/test_admin_console_settings.py tests/integration/app/test_system_router_extra.py -q`
- `uv run pytest tests/integration/app/test_api_server.py -q`

### Дальше

- Основной backend slice Phase 2 теперь закрыт: и `runtime.py`, и `settings.py` сведены к transport-level handlers поверх app-level services.
- Следующий практический шаг по плану — Phase 3: убрать дубли между setup/settings control-plane flows и вынести shared form primitives для operator UI.
- Внутри Phase 2 ещё остаётся необязательный follow-up:
  - при желании дальше дробить `AdminControlPlaneSettingsService` на более узкие доменные сервисы (`revisions`, `gigachat test`, `keys`);
  - но это уже можно делать только если появится реальный выигрыш по читаемости или по UI workflow.

## Phase 3

### Сделано

- Добавлен общий frontend binder `gpt2giga/frontend/admin/pages/control-plane-form-bindings.ts` для control-plane form workflow:
  - pending diff/status refresh;
  - inline validation;
  - save/persist flow;
  - GigaChat test-connection action.
- `render-setup.ts` и `render-settings.ts` переведены на этот общий binder вместо page-local дублирования submit/status logic.
- Вынесены observability secret/replace handlers в общий helper `bindObservabilitySecretFields(...)`, чтобы secret-field behavior не жил только внутри `render-settings.ts`.
- Упростил guided setup flow:
  - убрал observability controls из setup application step;
  - добавил отдельный `Optional · Observability` handoff card с live status по sink-ам и прямой ссылкой в `Settings → Observability`.
- Setup и Settings теперь читаются как разные workflow:
  - `Setup` ведёт через bootstrap-critical шаги;
  - `Settings` остаётся полноценным day-2 editor для grouped sections, включая observability.
- Пересобрал shipped admin assets в `packages/gpt2giga-ui/src/gpt2giga_ui/static/admin/`.

### Проверка

- `npm run build:admin`
- `uv run pytest tests/integration/app/test_admin_console_settings.py tests/integration/app/test_system_router_extra.py -q`

### Дальше

- Основной slice `Phase 3` начат и уже закрывает ключевую UX-проблему: setup больше не дублирует observability editor и использует те же control-plane form primitives, что и settings.
- Следующий практический шаг по плану — продолжить `Phase 3/4` на тяжёлых admin pages:
  - начать slice-архитектуру с `render-playground.ts`;
  - затем аналогично разрезать `logs`, `traffic`, `files-batches`.

## Phase 4

### Сделано

- Начат priority slice для тяжёлых admin pages с `playground`.
- `gpt2giga/frontend/admin/pages/render-playground.ts` сведён к тонкому page entrypoint:
  - загрузка `setup` payload;
  - рендер hero/content;
  - bind нового playground slice.
- Вынес playground page logic в отдельную модульную структуру `gpt2giga/frontend/admin/pages/playground/`:
  - `state.ts` для preset-ов, run-state и form field типов;
  - `serializers.ts` для request building, response parsing и SSE transcript helpers;
  - `api.ts` для fetch/SSE execution flow, abort/dispose lifecycle и transport orchestration;
  - `view.ts` для page layout, DOM lookup и panel/status rendering;
  - `bindings.ts` для form wiring, preset sync, validation и run/reset actions.
- Убрал из giant renderer-а page-local mutable state и scattered helper-ы:
  - active controller/run lifecycle;
  - request preview refresh;
  - run status panel updates;
  - preset activation logic;
  - SSE consumption helpers.
- После разреза `render-playground.ts` уменьшился примерно с `1268` строк до `34`, при этом shipped behavior страницы сохранён.
- Пересобрал shipped admin assets в `packages/gpt2giga-ui/src/gpt2giga_ui/static/admin/`, включая новый compiled subtree `pages/playground/`.
- Продолжил тот же slice-шаблон для `logs`.
- `gpt2giga/frontend/admin/pages/render-logs.ts` сведён к тонкому page entrypoint:
  - чтение query-driven filters;
  - загрузка initial logs payload;
  - рендер hero/content;
  - bind нового logs slice.
- Вынес logs page logic в отдельную модульную структуру `gpt2giga/frontend/admin/pages/logs/`:
  - `state.ts` для filters, stream-state и tail-context типов;
  - `serializers.ts` для URL/query helpers, tail-context extraction, selection summaries и stream diagnostics;
  - `api.ts` для initial fetch/tail refresh и SSE reader;
  - `view.ts` для page layout и DOM lookup;
  - `bindings.ts` для filter submit, selection inspector, local tail buffer и live stream lifecycle.
- Убрал из giant renderer-а page-local mutable state и transport helper-ы:
  - tail refresh/load flow;
  - SSE connect/stop/error handling;
  - tail-derived request context rendering;
  - selection inspector handoff между recent events и tail rows;
  - query-driven filter persistence.
- После разреза `render-logs.ts` уменьшился примерно с `1210` строк до `29`, при этом shipped behavior страницы сохранён.
- Пересобрал shipped admin assets в `packages/gpt2giga-ui/src/gpt2giga_ui/static/admin/`, включая новый compiled subtree `pages/logs/`.

### Проверка

- `npm run build:admin`
- `uv run pytest tests/integration/app/test_admin_console_settings.py tests/integration/app/test_system_router_extra.py -q`

### Дальше

- Уже два Phase 4 slice переведены на page-slice архитектуру: `playground` и `logs`.
- Следующий практический шаг по плану — продолжить тот же шаблон для оставшихся тяжёлых страниц:
  - `render-traffic.ts`;
  - затем `render-files-batches.ts`.
